import os
import cv2
import json
import time
import utils
import shutil
import argparse
import numpy as np
import pandas as pd
import scipy.misc
import torch
import torchvision
import torch.nn as nn
import torch.nn.parallel
import torch.optim as optim
import torch.nn.functional as F
import torchvision.models as models
import torch.backends.cudnn as cudnn

from torch.autograd import Variable
from torch.utils.data import sampler
from torchvision import datasets, transforms
from sklearn.utils import shuffle
from sklearn.model_selection import train_test_split
from models import *
from averagemeter import *

# GLOBAL CONSTANTS
DATA_FILE_TRAIN = 'leafsnap-dataset-train-images.csv'
DATA_FILE_TEST = 'leafsnap-dataset-test-images.csv'
NB_EPOCH = 50
INPUT_SIZE = 224
NUM_CLASSES = 185
NUM_EPOCHS = 30
LEARNING_RATE = 1e-1
USE_CUDA = torch.cuda.is_available()
best_prec1 = 0

# ARGS Parser
parser = argparse.ArgumentParser(description='PyTorch LeafSnap Training')
parser.add_argument('--resume', default='', type=str, metavar='PATH',
                    help='path to latest checkpoint (default: none)')
args = parser.parse_args()

# Training method which trains model for 1 epoch
def train(train_loader, model, criterion, optimizer, epoch):
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()

    # switch to train mode
    model.train()

    end = time.time()
    for i, (input, target) in enumerate(train_loader):
        # measure data loading time
        if USE_CUDA:
            input = input.cuda(async=True)
            target = target.cuda(async=True)

        data_time.update(time.time() - end)

        input_var = torch.autograd.Variable(input)
        target_var = torch.autograd.Variable(target)

        # compute output
        output = model(input_var)
        loss = criterion(output, target_var)

        # measure accuracy and record loss
        prec1, prec5 = accuracy(output.data, target, topk=(1, 5))
        losses.update(loss.data[0], input.size(0))
        top1.update(prec1[0], input.size(0))
        top5.update(prec5[0], input.size(0))

        # compute gradient and do SGD step
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % 10 == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                  '\Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Prec@1 {top1.val:.3f} ({top1.avg:.3f})\t'
                  'Prec@5 {top5.val:.3f} ({top5.avg:.3f})'.format(
                   epoch, i, len(train_loader), batch_time=batch_time,
                   data_time=data_time, loss=losses, top1=top1, top5=top5))

# Validation method
def validate(val_loader, model, criterion):
    batch_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()

    # switch to evaluate mode
    model.eval()

    end = time.time()
    for i, (input, target) in enumerate(val_loader):
        if USE_CUDA:
            input = input.cuda(async=True)
            target = target.cuda(async=True)
        input_var = torch.autograd.Variable(input, volatile=True)
        target_var = torch.autograd.Variable(target, volatile=True)

        # compute output
        output = model(input_var)
        loss = criterion(output, target_var)

        # measure accuracy and record loss
        prec1, prec5 = accuracy(output.data, target, topk=(1, 5))
        losses.update(loss.data[0], input.size(0))
        top1.update(prec1[0], input.size(0))
        top5.update(prec5[0], input.size(0))

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % 10 == 0:
            print('Test: [{0}/{1}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Prec@1 {top1.val:.3f} ({top1.avg:.3f})\t'
                  'Prec@5 {top5.val:.3f} ({top5.avg:.3f})'.format(
                   i, len(val_loader), batch_time=batch_time, loss=losses,
                   top1=top1, top5=top5))

    print(' * Prec@1 {top1.avg:.3f} Prec@5 {top5.avg:.3f}'
          .format(top1=top1, top5=top5))

    return top1.avg

def save_checkpoint(state, is_best, filename='checkpoint.pth.tar'):
    torch.save(state, filename)
    if is_best:
        shutil.copyfile(filename, 'model_best.pth.tar')

def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    lr = LEARNING_RATE * (0.1 ** (epoch // 10))
    # decay = LEARNING_RATE / NUM_EPOCHS
    # lr = lr * 1/(1 + decay * epoch)
    # if (lr <= 0.0001):
    #     lr = 0.0001
    print('\n[Learning Rate] {:0.4f}'.format(lr))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr

def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].view(-1).float().sum(0)
        res.append(correct_k.mul_(100.0 / batch_size))
    return res

print('\n[INFO] Creating Model')
model = VGG('VGG16')
# model = resnet50()
# model = densenet121()

print('\n[INFO] Model Architecture: \n{}'.format(model))

criterion = nn.CrossEntropyLoss()
if USE_CUDA:
     model = torch.nn.DataParallel(model).cuda()
     criterion = criterion.cuda()
optimizer = optim.SGD(model.parameters(), lr=LEARNING_RATE, momentum=0.9, weight_decay=1e-4)

if args.resume:
    if os.path.isfile(args.resume):
        print("=> loading checkpoint '{}'".format(args.resume))
        checkpoint = torch.load(args.resume)
        args.start_epoch = checkpoint['epoch']
        best_prec1 = checkpoint['best_prec1']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        print("=> loaded checkpoint '{}' (epoch {})"
              .format(args.resume, checkpoint['epoch']))
    else:
        print("=> no checkpoint found at '{}'".format(args.resume))

print('\n[INFO] Reading Training and Testing Dataset')
traindir = os.path.join('dataset', 'train')
testdir = os.path.join('dataset', 'test')
normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225])
data_train = datasets.ImageFolder(traindir, transforms.Compose([
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalize]))
data_test = datasets.ImageFolder(testdir, transforms.Compose([
            transforms.ToTensor(),
            normalize]))


train_loader = torch.utils.data.DataLoader(data_train, batch_size=64, shuffle=True, num_workers=2)
val_loader = torch.utils.data.DataLoader(data_test, batch_size=64, shuffle=False, num_workers=2)

print('\n[INFO] Training Started')
for epoch in range(1, NUM_EPOCHS+1):
    adjust_learning_rate(optimizer, epoch)

    # train for one epoch
    train(train_loader, model, criterion, optimizer, epoch)
    # evaluate on validation set
    prec1 = validate(val_loader, model, criterion)

    # remember best prec@1 and save checkpoint
    is_best = prec1 > best_prec1
    best_prec1 = max(prec1, best_prec1)
    save_checkpoint({
        'epoch': epoch + 1,
        'state_dict': model.state_dict(),
        'best_prec1': best_prec1,
        'optimizer' : optimizer.state_dict(),
    }, is_best)
    # print('\n[INFO] Saved Model to leafsnap_model.pth')
    # torch.save(model, 'leafsnap_model.pth')

print('\n[DONE]')
