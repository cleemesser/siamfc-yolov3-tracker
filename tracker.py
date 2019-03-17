import os
import glob
from random import randint
import cv2
from yolov3.detect import yolo, prepare_model
from siamfc.siamfc import SiamFCTracker


class bbox():
    def __init__(self, box, colour, tracker, id):
        self.id = id
        self.box = box
        self.colour = colour
        self.tracker = tracker
        self.mid_points = []

    def convert_xywh_to_xyxy(self):
        self.box = self.box[0]-1, self.box[1]-1, self.box[0] + \
            self.box[2]-1, self.box[1]+self.box[3]-1

    def convert_xyxy_to_xywh(self):
        self.box = self.box[0]+1, self.box[1]+1, self.box[2] - \
            self.box[0]+1, self.box[3]-self.box[1]+1

    def mid_point(self):
        # bbox: one-based bounding box[x1, y1, x2, y2]
        return (int((self.box[0] + self.box[2])/2),
                int((self.box[1] + self.box[3])/2))

    def add_mid_point(self):
        self.mid_points.append(self.mid_point())

    def init_box(self, frame):
        """
        bbox: one-based bounding box[x, y, width, height]
        input should be one-based. It makes the conversion to zero based inside init function
        output of yolo is already one-based
        """
        self.tracker.init(frame, self.box)
        self.convert_xywh_to_xyxy()
        self.add_mid_point()


class Tracker():
    def __init__(self, model_path='siamfc/models/siamfc_pretrained.pth', gpu_id=0):
        self.model_path = model_path
        self.gpu_id = gpu_id
        self.filenames = ''
        self.model, self.inp_dim = prepare_model()

        self.DETECT_PER_FRAME = 5
        self.UPPER_THRESHOLD = 0.8
        self.LOWER_THRESHOLD = 0.1

    def get_filenames_frames(self, video_dir):
        filenames = sorted(glob.glob(os.path.join(video_dir, "img/*.jpg")),
                           key=lambda x: int(os.path.basename(x).split('.')[0]))
        if len(filenames) == 0:
            filenames = sorted(glob.glob(os.path.join(video_dir, "*.jpg")),
                               key=lambda x: int(os.path.basename(x).split('.')[0]))
        frames = [cv2.cvtColor(cv2.imread(filename), cv2.COLOR_BGR2RGB)
                  for filename in filenames]
        return filenames, frames

    def convert_xywh_to_xyxy(self, yolo):
        return (yolo[0]-1, yolo[1]-1, yolo[0]+yolo[2]-1, yolo[1]+yolo[3]-1)

    def convert_xyxy_to_xywh(self, yolo):
        return (yolo[0]+1, yolo[1]+1, yolo[2]-yolo[0]+1, yolo[3]-yolo[1]+1)

    def draw_frame(self, bboxes, frame, frame_id):
        for b, bbox in enumerate(bboxes):
            # draw rectangle bbox:[x1,y1,x2,y2]
            frame = cv2.rectangle(frame,
                                  (int(bbox.box[0]), int(bbox.box[1])),
                                  (int(bbox.box[2]), int(bbox.box[3])),
                                  bbox.colour,
                                  2)
            # add line between each frame
            mid_point = bbox.mid_point()
            for m in range(1, len(bbox.mid_points) - 1):
                if m != 0:
                    frame = cv2.line(
                        frame, bbox.mid_points[m-1], bbox.mid_points[m], bbox.colour)
        if len(frame.shape) == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        cv2.putText(frame, str(frame_id), (5, 20),
                    cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (0, 255, 0), 1)
        return frame

    def detect(self, idx):
        person_detections = list(set(
            filter(lambda x: x[1] == 'person', yolo(self.filenames[idx], self.model, self.inp_dim))))
        person_detections.sort(key=lambda x: (
            x[0][2] * x[0][3]), reverse=True)

        return person_detections

    def track(self, video_dir):
        # load videos
        self.filenames, frames = self.get_filenames_frames(video_dir)
        video_dir_list = video_dir.split('/')
        if video_dir_list[-1] == "":
            video_dir_list.remove("")
        
        title = video_dir_list[-1]
        if "MOT16" in video_dir_list:
            title = video_dir_list[len(video_dir_list) - 2]
        # starting tracking

        
        bboxes = []
        person_detections = []
        person_id = 0

        for idx, frame in enumerate(frames):

            if idx == 0:
                first_detections = self.detect(0)
                for i, ix in enumerate(first_detections):
                    box = bbox(ix[0], (randint(0, 255) % 255, randint(0, 255), randint(
                        0, 255)), SiamFCTracker(self.model_path, self.gpu_id), person_id)
                    person_id += 1
                    box.init_box(frame)
                    bboxes.append(box)

            if idx % self.DETECT_PER_FRAME == 0:
                person_detections = self.detect(idx)
                for c, cbox in enumerate(bboxes):
                    best_iou = -1
                    best_box = None
                    best_person = None
                    for p, person in enumerate(person_detections):
                        pbox = person[0]
                        # cbox.box = xyxy
                        # pbox = xywh
                        # iou takes xyxy, xyxy
                        iou = self.bb_intersection_over_union(
                            cbox.box, self.convert_xywh_to_xyxy(pbox))
                        if iou > best_iou:
                            best_iou = iou
                            best_box = pbox
                            best_person = person

                    if best_iou > self.UPPER_THRESHOLD:
                        # best_box = xywh
                        cbox.box = best_box
                        cbox.init_box(frame)
                        person_detections.remove(best_person)

                    elif best_iou < self.LOWER_THRESHOLD:
                        bboxes.remove(cbox)
                    else:
                        person_detections.remove(best_person)

                for p, person in enumerate(person_detections):
                    box = bbox(person[0],
                               (randint(0, 255) %
                                255, randint(0, 255), randint(0, 255)),
                               SiamFCTracker(self.model_path, self.gpu_id),
                               person_id)
                    person_id += 1
                    box.init_box(frame)
                    bboxes.append(box)

            else:
                for c, cbox in enumerate(bboxes):
                    # bounding box[x1, y1, x2, y2]
                    cbox.box = cbox.tracker.update(frame, idx)
                    cbox.add_mid_point()
            # bbox xmin ymin xmax ymax

            frame = self.draw_frame(bboxes, frame, idx)
            cv2.imshow(title, frame)
            cv2.imwrite(os.getcwd() + '/dets/' + title +'/det_'+str(idx) + '.jpg', frame)
            cv2.waitKey(30)

        self.images_to_video(title)

    def bb_intersection_over_union(self, boxA, boxB):
        """
        bbox: one-based bounding box[x1, y1, x2, y2] is the input
        """

        # determine the (x, y)-coordinates of the intersection rectangle
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        # compute the area of intersection rectangle
        interArea = max(0, xB - xA + 1) * max(0, yB - yA + 1)

        # compute the area of both the prediction and ground-truth
        # rectangles
        boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
        boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)

        # compute the intersection over union by taking the intersection
        # area and dividing it by the sum of prediction + ground-truth
        # areas - the interesection area
        iou = interArea / float(boxAArea + boxBArea - interArea)

        # return the intersection over union value
        return iou

    def images_to_video(self, title):
        img_array = []
        for filename in glob.glob(os.getcwd() + '/dets/' + title + '/*.jpg'):
            img = cv2.imread(filename)
            height, width, layers = img.shape
            size = (width, height)
            img_array.append(img)

        out = cv2.VideoWriter(
            title + '.avi', cv2.VideoWriter_fourcc(*'DIVX'), 15, size)

        for i in range(len(img_array)):
            out.write(img_array[i])
        out.release()
