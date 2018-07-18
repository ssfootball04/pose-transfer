import sys

# shitty thing overriding src code in current dir
if('/home/anurag/multiperson/detectron/lib' in sys.path):
    sys.path.remove('/home/anurag/multiperson/detectron/lib')

import matplotlib
matplotlib.use('Agg')
import pylab as plt
import os
import sys
import torch
import numpy as np
import cv2
import time
import datetime
from opts import opts
# from tqdm import tqdm
from datasets.PoseTransfer_Dataset import PoseTransfer_Dataset
from models.networks import Deformable_Generator, Discriminator
from models.pose_gan import DeformablePose_GAN
from utils import pose_utils

def load_sample(iter,dataloader,name, gen_type):
    if (gen_type == 'baseline'):
        try:
            input, target, warps, masks = iter.next()
        except:
            # resetting iterator
            print("Resetting iterator for loader :", name)
            iter = dataloader.__iter__()
            input, target, warps, masks = iter.next()
        return input, target, warps, masks, iter
    elif (gen_type == 'stacked'):
        try:
            input, target, interpol_pose, interpol_warps, interpol_masks = iter.next()
        except:
            # resetting iterator
            print("Resetting iterator for loader :", name)
            iter = dataloader.__iter__()
            input, target, interpol_pose, interpol_warps, interpol_masks  = iter.next()
        return input, target, interpol_pose, interpol_warps, interpol_masks, iter

def main():
  opt = opts().parse()
  print("Model options . .")
  for k, v in sorted(vars(opt).items()):
      print('  %s: %s' % (str(k), str(v)))

  loader_train = torch.utils.data.DataLoader(
      PoseTransfer_Dataset(vars(opt), split ='train'),
      batch_size = opt.batch_size,
      shuffle = True,
  )

  loader_test = torch.utils.data.DataLoader(
      PoseTransfer_Dataset(vars(opt), split='test'),
      batch_size=opt.batch_size,
      shuffle=True,
  )

  model = DeformablePose_GAN(opt).cuda()
  start_epoch = 1
  if(opt.resume==1):
      start_epoch = model.resume(opt.checkpoints_dir)

  # discriminator and generator updates; iterators initialized out of epoch loop
  loader_train_iter = loader_train.__iter__()
  loader_test_iter = loader_test.__iter__()
  for epoch in range(start_epoch, opt.number_of_epochs + 1):
      # num_iter = len(gen_loader_train)
      gen_losses, disc_losses = [], []
      num_iterations = opt.iters_per_epoch
      print("Num iterations : ", num_iterations)

      # note warps must be converted into float
      for it in range(num_iterations):
          for _ in range(opt.training_ratio):
              if(opt.gen_type=='baseline'):

                  input, target, warps, masks, loader_train_iter = load_sample(loader_train_iter, loader_train, 'train', opt.gen_type)
                  real_inp, real_target, _, _, loader_train_iter = load_sample(loader_train_iter, loader_train, 'train', opt.gen_type)
                  other_inputs = {'warps': warps.float().cuda(), 'masks': masks.cuda()}

                  disc_loss = model.dis_update(input.cuda(),target.cuda(), other_inputs,
                                   real_inp.cuda(), real_target.cuda(), vars(opt))
                  disc_losses.append(disc_loss)

              elif (opt.gen_type == 'stacked'):

                  input, target, interpol_pose, interpol_warps, interpol_masks, loader_train_iter = load_sample(loader_train_iter, loader_train, 'train', opt.gen_type)
                  other_inputs = {'interpol_pose' : interpol_pose.cuda(), 'interpol_warps': interpol_warps.float().cuda(), 'interpol_masks': interpol_masks.cuda()}
                  real_inp, real_target, _, _,_, loader_train_iter = load_sample(loader_train_iter, loader_train, 'train', opt.gen_type)

                  # debugging statements
                  # print(interpol_warps.shape)
                  # print(interpol_masks.shape)

                  disc_loss = model.dis_update(input.cuda(), target.cuda(), other_inputs,
                                   real_inp.cuda(), real_target.cuda(), vars(opt))
                  disc_losses.append(disc_loss)

          if (opt.gen_type == 'baseline'):

              input, target, warps, masks, loader_train_iter = load_sample(loader_train_iter, loader_train, 'train', opt.gen_type)
              other_inputs = { 'warps' : warps.float().cuda(), 'masks' : masks.cuda() }
              out, outputs, gen_loss = model.gen_update(input.cuda(), target.cuda(), other_inputs, vars(opt))
              gen_losses.append(gen_loss)

          elif (opt.gen_type == 'stacked'):

              input, target, interpol_pose, interpol_warps, interpol_masks, loader_train_iter = load_sample(loader_train_iter, loader_train, 'train', opt.gen_type)
              other_inputs = {'interpol_pose': interpol_pose.cuda(), 'interpol_warps': interpol_warps.float().cuda(), 'interpol_masks': interpol_masks.cuda()}
              out, outputs, gen_loss = model.gen_update(input.cuda(), target.cuda(), other_inputs, vars(opt))
              gen_losses.append(gen_loss)

          if(it%opt.display_ratio==0):

              # print losses
              # edit later to visualize easily
              gen_total_loss, gen_ll_loss, gen_ad_loss = np.mean(np.array(gen_losses), axis=0)
              disc_total_loss, disc_true_loss, disc_fake_loss = np.mean(np.array(disc_losses), axis=0)
              total_loss = gen_total_loss + disc_total_loss
              print("Epoch : {8:d} | Progress : {0:.2f} | Total Loss : {1:.4f} | Gen Total Loss : {2:.4f}, Gen Ad Loss : {3:.4f}, Gen LL Loss : {4:.4f}  | Disc Total Loss : {5:.4f}, Disc True Loss : {6:.4f}, Disc Fake Loss : {7:.4f} ".format(it/num_iterations, total_loss, gen_total_loss, gen_ad_loss, gen_ll_loss, disc_total_loss, disc_true_loss, disc_fake_loss, epoch))

              # required to intermittently print output when using nohup
              sys.stdout.flush()

              # saving seen images

              if(opt.gen_type=='baseline'):
                images = pose_utils.display(input,target,out.data.cpu(),opt.use_input_pose,opt.pose_dim)
              else:
                images = pose_utils.display_stacked(input, interpol_pose, target, outputs, opt.num_stacks, opt.use_input_pose, opt.pose_dim)

              title = "epoch_{0}_{1}.png".format(str(epoch).zfill(3), str(it).zfill(5))
              plt.imsave(os.path.join(opt.output_dir, 'train', title), images, cmap=plt.cm.gray)

              # saving results for unseen images

              if(opt.gen_type=='baseline'):
                  input, target, warps, masks, loader_test_iter = load_sample(loader_test_iter, loader_test, 'test', opt.gen_type)
                  out = model.gen(input.cuda(), warps.float().cuda(), masks.cuda())
                  images = pose_utils.display(input, target, out.data.cpu(), opt.use_input_pose, opt.pose_dim)

              elif(opt.gen_type=='stacked'):
                  input, target, interpol_pose, interpol_warps, interpol_masks, loader_test_iter = load_sample(loader_test_iter, loader_test, 'test', opt.gen_type)
                  out = model.gen(input.cuda(),interpol_pose.cuda(), interpol_warps.float().cuda(), interpol_masks.cuda())
                  images = pose_utils.display_stacked(input, interpol_pose, target, out, opt.num_stacks, opt.use_input_pose, opt.pose_dim)

              else:
                  raise Exception('Invalid gen type !!')
              title = "epoch_{0}_{1}.png".format(str(epoch).zfill(3), str(it).zfill(5))
              plt.imsave(os.path.join(opt.output_dir, 'test', title), images, cmap=plt.cm.gray)

      if(epoch%opt.checkpoint_ratio==0):
          model.save(opt.checkpoints_dir, epoch)

main()