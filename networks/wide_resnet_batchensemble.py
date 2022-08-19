import torch
import torch.nn as nn
import torch.nn.init as init
import torch.nn.functional as F
from torch.autograd import Variable
from networks.batchensemble_layers import *

import sys
import numpy as np

def conv3x3(in_planes, out_planes, stride=1,first_layer=False,num_models=4):
    return Ensemble_Conv2d(in_planes, out_planes, 3, stride=stride, padding=1, first_layer=first_layer, num_models=num_models)


def conv_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        try:
            init.xavier_uniform_(m.conv.conv.weight, gain=np.sqrt(2))
        except:
            init.xavier_uniform_(m.weight, gain=np.sqrt(2))
            #init.constant_(m.bias, 0)
    elif classname.find('BatchNorm') != -1:
        init.constant_(m.weight, 1)
        init.constant_(m.bias, 0)

class wide_basic_ensemble(nn.Module):
    def __init__(self, in_planes, planes, dropout_rate, stride=1,num_models=4):
        super(wide_basic_ensemble, self).__init__()
        self.bn1 = nn.BatchNorm2d(in_planes)
        #self.conv1 = nn.Conv2d(in_planes, planes, kernel_size=3, padding=1, bias=True)
        self.conv1 = Ensemble_Conv2d(in_planes, planes, 3, stride=1, padding=1, first_layer=False, num_models=num_models, bias=True)
        ##self.conv1 = Ensemble_Conv2dBatchNorm_pre(in_planes, planes, 3, stride=1, padding=1, first_layer=False, num_models=num_models, bias=True)
        self.dropout = nn.Dropout(p=dropout_rate)
        self.bn2 = nn.BatchNorm2d(planes)
        #self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride, padding=1, bias=True)
        self.conv2 = Ensemble_Conv2d(planes, planes, 3, stride=stride, padding=1, first_layer=False, num_models=num_models, bias=True)
        ##self.conv2 = Ensemble_Conv2dBatchNorm_pre(planes, planes, 3, stride=stride, padding=1, first_layer=False, num_models=num_models, bias=True)
        self.num_models=num_models
        self.convs=[self.conv1,self.conv2]
        self.shortcut = nn.Sequential()
        if stride != 1 or in_planes != planes:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_planes, planes, kernel_size=1, stride=stride, bias=True),
                #Ensemble_Conv2d(in_planes, planes, 1, stride=stride, padding=0, first_layer=False, num_models=num_models, bias=True),
            )
    def update_indices(self, indices):
        for m_conv in self.convs:
            m_conv.update_indices(indices)

    def forward(self, x):
        curr_bs = x.size(0)
        out = self.dropout(self.conv1(F.relu(self.bn1(x))))
        out = self.conv2(F.relu(self.bn2(out)))
        out += self.shortcut(x)

        return out

class wide_basic(nn.Module):
    def __init__(self, in_planes, planes, dropout_rate, stride=1,num_models=1):
        super(wide_basic, self).__init__()
        self.bn1 = nn.BatchNorm2d(in_planes)
        self.conv1 = nn.Conv2d(in_planes, planes, kernel_size=3, padding=1, bias=True)
        self.dropout = nn.Dropout(p=dropout_rate)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride, padding=1, bias=True)
        self.shortcut = nn.Sequential()
        if stride != 1 or in_planes != planes:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_planes, planes, kernel_size=1, stride=stride, bias=True),
            )

    def forward(self, x):
        out = self.dropout(self.conv1(F.relu(self.bn1(x))))
        out = self.conv2(F.relu(self.bn2(out)))
        out += self.shortcut(x)

        return out

class Wide_ResNet_BatchEnsemble(nn.Module):
    def __init__(self, depth, widen_factor, dropout_rate, num_classes,num_models):
        super(Wide_ResNet_BatchEnsemble, self).__init__()
        self.in_planes = 16
        self.num_models = num_models
        assert ((depth-4)%6 ==0), 'Wide-resnet depth should be 6n+4'
        n = (depth-4)/6
        k = widen_factor

        print('| Wide-Resnet %dx%d' %(depth, k))
        nStages = [16, 16*k, 32*k, 64*k]

        self.conv1 = conv3x3(3,nStages[0], stride=1,first_layer=True, num_models=num_models)
        self.layer1 = self._wide_layer(wide_basic_ensemble, nStages[1], n, dropout_rate, stride=1,num_models=num_models)
        self.layer2 = self._wide_layer(wide_basic_ensemble, nStages[2], n, dropout_rate, stride=2,num_models=num_models)
        self.layer3 = self._wide_layer(wide_basic_ensemble, nStages[3], n, dropout_rate, stride=2,num_models=num_models)
        self.bn1 = nn.BatchNorm2d(nStages[3], momentum=0.9)
        #self.linear = nn.Linear(nStages[3], num_classes)
        self.linear =Ensemble_orderFC(nStages[3], num_classes, num_models, False)
        self.num_classes = num_classes
    def _wide_layer(self, block, planes, num_blocks, dropout_rate, stride,num_models):
        strides = [stride] + [1]*(int(num_blocks)-1)
        layers = []

        for stride in strides:
            layers.append(block(self.in_planes, planes, dropout_rate, stride,num_models))
            self.in_planes = planes

        return nn.Sequential(*layers)

    def forward(self, x):
        out = self.conv1(x)
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = F.relu(self.bn1(out))
        out = F.avg_pool2d(out, 8)
        out = out.view(out.size(0), -1)
        out = self.linear(out)
        if not self.training:
            out=F.softmax(out, dim=1)
            return out.view([self.num_models, -1, self.num_classes]).mean(dim=0)

        return out

if __name__ == '__main__':
    net=Wide_ResNet_BatchEnsemble(28, 10, 0.3, 10)
    y = net(Variable(torch.randn(1,3,32,32)))

    print(y.size())
