import sys

if sys.version_info[0] < 3 and sys.version_info[1] < 2:
	raise Exception("Must be using >= Python 3.2")

from os import listdir, path

if not path.isfile('face_detection/detection/sfd/s3fd.pth'):
	raise FileNotFoundError('Save the s3fd model to face_detection/detection/sfd/s3fd.pth \
							before running this script!')

import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import argparse, os, cv2, traceback, subprocess
from tqdm import tqdm
from glob import glob
import audio
from hparams import hparams as hp
from hparams import get_image_list

import face_detection

parser = argparse.ArgumentParser()

parser.add_argument('--ngpu', help='Number of GPUs across which to run in parallel', default=1, type=int)
parser.add_argument('--batch_size', help='Single GPU Face detection batch size', default=32, type=int)
parser.add_argument("--data_root", help="Root folder of the LRS2 dataset", required=True)
parser.add_argument("--subset", help="sub folder to process", required=True)
parser.add_argument("--preprocessed_root", help="Root folder of the preprocessed dataset", required=True)

args = parser.parse_args()

fa = [face_detection.FaceAlignment(face_detection.LandmarksType._2D, flip_input=False, 
									device='cuda:{}'.format(id)) for id in range(args.ngpu)]

template = 'ffmpeg -loglevel panic -y -i {} -strict -2 {}'
# template2 = 'ffmpeg -hide_banner -loglevel panic -threads 1 -y -i {} -async 1 -ac 1 -vn -acodec pcm_s16le -ar 16000 {}'

def process_video_file(vfile, args, gpu_id):
	video_stream = cv2.VideoCapture(vfile)
	
	frames = []
	while 1:
		still_reading, frame = video_stream.read()
		if not still_reading:
			video_stream.release()
			break
		frames.append(frame)
	
	vidname = os.path.basename(vfile).split('.')[0]
	dirname = args.subset

	fulldir = path.join(args.preprocessed_root, dirname, vidname)
	os.makedirs(fulldir, exist_ok=True)

	batches = [frames[i:i + args.batch_size] for i in range(0, len(frames), args.batch_size)]

	i = -1
	for fb in batches:
		preds = fa[gpu_id].get_detections_for_batch(np.asarray(fb))

		for j, f in enumerate(preds):
			i += 1
			if f is None:
				continue

			x1, y1, x2, y2 = f
			cv2.imwrite(path.join(fulldir, '{}.jpg'.format(i)), fb[j][y1:y2, x1:x2])

def process_audio_file(vfile, args):
	vidname = os.path.basename(vfile).split('.')[0]
	print("   "  + vfile)
	dirname = args.subset

	fulldir = path.join(args.preprocessed_root, dirname, vidname)

	print(fulldir.__str__())
	os.makedirs(fulldir, exist_ok=True)

	wavpath = path.join(fulldir, 'audio.wav')
	print(wavpath)

	command = template.format(vfile, wavpath)
	# subprocess.call(command, shell=True)
	proc = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	proc.wait()
	(stdout, stderr) = proc.communicate()

	if proc.returncode != 0:
		print(stderr)
	else:
		print("success")

	
def mp_handler(job):
	vfile, args, gpu_id = job
	try:
		process_video_file(vfile, args, gpu_id)
	except KeyboardInterrupt:
		exit(0)
	except:
		traceback.print_exc()
		
def main(args):
	print('Started processing for {} with {} GPUs'.format(args.data_root, args.ngpu))

	filelistDataRoot = glob(path.join(args.data_root, '*.mp4'))

	alreadyProccedFileList = get_image_list(args.preprocessed_root, args.subset)

	fileList = []

	for i in range(len(filelistDataRoot)):
		name = filelistDataRoot[i].split(sep='/')[2].split(sep=".")[0]
		if name not in alreadyProccedFileList:
			fileList.append(filelistDataRoot[i])

	print("filelistDataRoot ", len(filelistDataRoot))
	print("alreadyProccedFileList ", len(alreadyProccedFileList))
	print("filelist ", len(fileList))

	jobs = [(vfile, args, i%args.ngpu) for i, vfile in enumerate(fileList)]
	p = ThreadPoolExecutor(args.ngpu)
	futures = [p.submit(mp_handler, j) for j in jobs]
	_ = [r.result() for r in tqdm(as_completed(futures), total=len(futures))]

	print('Dumping audios...')
	print(filelistDataRoot.count)

	for vfile in tqdm(filelistDataRoot, total=filelistDataRoot.count):
		try:
			process_audio_file(vfile, args)
		except KeyboardInterrupt:
			exit(0)
		except:
			traceback.print_exc()
			continue

if __name__ == '__main__':
	main(args)