import json
import trt_pose.coco
import trt_pose.models
import torch
import torch2trt
from torch2trt import TRTModule
import time
import cv2
import torchvision.transforms as transforms
import PIL.Image
from trt_pose.draw_objects import DrawObjects
from trt_pose.parse_objects import ParseObjects

import argparse
from os import path


DIR_DATASETS = '../datasets/'
DIR_PRETRAINED_MODELS = '../pretrained-models/'

DATASET = 'human_pose_new.json'

MODEL_RESNET18 = 'resnet18_crowdpose_224x224_epoch_129.pth'
OPTIMIZED_MODEL_RESNET18 = 'resnet18_crowdpose_224x224_epoch_129_trt.pth'

WIDTH = 224
HEIGHT = 224

parser = argparse.ArgumentParser(description='TensorRT pose estimation run')
parser.add_argument('--video', type=str, default='video.mp4')
parser.add_argument('--path', type=str, default='/videos/')
args = parser.parse_args()

splited_video= args.video.split('.')
video_name = splited_video[0]


def preprocess(image):
    global device
    device = torch.device('cuda')
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image = PIL.Image.fromarray(image)
    image = transforms.functional.to_tensor(image).to(device)
    image.sub_(mean[:, None, None]).div_(std[:, None, None])
    return image[None, ...]


def initialize_video_writer():
    print('initialize video capture')
    capture = cv2.VideoCapture(args.path + args.video)
    fourcc = cv2.VideoWriter_fourcc('m', 'p', '4', 'v')
    frame_width = int(capture.get(3) * 0.5)
    frame_height = int(capture.get(4) * 0.5)
    frame_size = (frame_width, frame_height)
    print('initialize video writer')
    out_vid = cv2.VideoWriter(args.path + MODEL_RESNET18 + '_' + video_name + '_demo.mp4', fourcc, 25, frame_size)

    return capture, out_vid, frame_size


def clean_up():
    cv2.destroyAllWindows()
    out_video.release()
    cap.release()
    print('all released')


def execute(image, src, tm, out_vid, counter):
    img_data = preprocess(image)
    cmap, paf = model_trt(img_data)
    cmap, paf = cmap.detach().cpu(), paf.detach().cpu()
    counts, objects, peaks = parse_objects(cmap, paf)
    fps = counter / (time.time() - tm)
    print("FPS:%f " % fps)
    draw_objects(src, counts, objects, peaks)
    cv2.putText(src, "FPS: %f" % fps, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    out_vid.write(src)


def process_frames(out_video, cap, frame_size):
    i = 1
    t = time.time()

    while cap.isOpened():
        if i % 4 is 3:
            ret, frame = cap.read()

            if not ret:
                print("End of videofile.")
                break

            if cv2.waitKey(25) & 0xFF == ord('q'):
                break

            frame_resized = cv2.resize(frame, frame_size, interpolation=cv2.INTER_LINEAR)
            img = cv2.resize(frame, dsize=(WIDTH, HEIGHT), interpolation=cv2.INTER_LINEAR)
            execute(img, frame_resized, t, out_video, i)
        i += 1

#loads the JSON file which describes the human pose task
with open(DIR_DATASETS + DATASET, 'r') as f:
    human_pose = json.load(f)

topology = trt_pose.coco.coco_category_to_topology(human_pose)

#loads the model
num_parts = len(human_pose['keypoints'])
num_links = len(human_pose['skeleton'])

model = trt_pose.models.resnet18_baseline_att(num_parts, 2 * num_links).cuda().eval()

data = torch.zeros((1, 3, HEIGHT, WIDTH)).cuda()

#convert the model from PyTorch to TensorRT and save it in the pretrained-models folder
if not path.exists(DIR_PRETRAINED_MODELS + OPTIMIZED_MODEL_RESNET18):
    print('Start converting model to trt')
    model.load_state_dict(torch.load(DIR_PRETRAINED_MODELS + MODEL_RESNET18))
    model_trt = torch2trt.torch2trt(model, [data], fp16_mode=True, max_workspace_size=1<<25)
    torch.save(model_trt.state_dict(), DIR_PRETRAINED_MODELS + OPTIMIZED_MODEL_RESNET18)
    print('Model optimized')

#loads the saved TensorRT model
model_trt = TRTModule()
model_trt.load_state_dict(torch.load(DIR_PRETRAINED_MODELS + OPTIMIZED_MODEL_RESNET18))

mean = torch.Tensor([0.485, 0.456, 0.406]).cuda()
std = torch.Tensor([0.229, 0.224, 0.225]).cuda()
device = torch.device('cuda')

#defines to classes that will be used to parse the objects from the neural network and to draw the parsed object on frames
parse_objects = ParseObjects(topology)
draw_objects = DrawObjects(topology)

#initializes the video capturing and writing and processes the frames
cap, out_video, frame_size = initialize_video_writer()
process_frames(out_video, cap, frame_size)

clean_up()
print("Process finished")

