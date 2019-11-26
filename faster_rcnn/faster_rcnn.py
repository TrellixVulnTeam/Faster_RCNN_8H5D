"""
Faster R-CNN
Faster R-CNN Network.

Copyright (c) 2019 Haohang Huang
Licensed under the MIT License (see LICENSE for details)
Written by Haohang Huang, November 2019.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np

from config import Config as cfg
from resnet import resnet_loader
from rpn.rpn import RPN
from roi_pooling import RoIPooling
from classification import Classification

class FasterRCNN(nn.Module):
    """Faster Regional-CNN
    """
    def __init__(self):
        super(FasterRCNN, self).__init__()

        resnet = resnet_loader(arch='resnet101', pretrained=True)
        # Part 1 layers from ResNet as feature extraction network
        self.cnn1 = nn.Sequential(
            resnet.conv1,
            resnet.bn1,
            resnet.relu,
            resnet.maxpool,
            resnet.layer1,
            resnet.layer2,
            resnet.layer3
        )
        # Freeze all pretrained layers
        for param in self.cnn1.parameters():
            param.requires_grad = False

        # RPN network
        self.rpn = RPN()

        # RoI Pooling
        self.pooling = RoIPooling()

        # Part 2 layers from ResNet
        self.cnn2 = nn.Sequential(
            resnet.layer4,
            nn.AvgPool2d(cfg.POOLING_SIZE) # 7
        )
        # This layer works on a different input feature maps, so I think it's better to train it
        # for param in self.cnn2.parameters():
        #     param.requires_grad = False

        # Classification network
        self.classification = Classification(self.cnn2) # include cnn2 in the classification network

    def forward(self, images, gt_boxes, gt_classes):
        """Forward step.
        Args:
            images [N x H x W]: N input images
            gt_boxes [N x X x 4]: ground-truth boxes in each image. Only used in AnchorRefine & ProposalRefine layers.
            gt_classes [N x X]: classes of ground-truth boxes in each image. Only used in ProposalRefine layer.
        Returns:
            rois [N x R x 4]:
            pred_rois_classes [N x R]:
            pred_rois_coeffs [N x R x 21*4]:
            rcnn_loss [float]: RCNN total loss
        """
        # 1. head CNN network (ResNet)
        feature_map = self.cnn1(images) # N x C x H x W

        # 2. RPN network
        rois, gt_rois_labels, gt_rois_coeffs, rpn_loss = self.rpn(feature_map, gt_boxes, gt_classes)
        # rois: N x R x 4
        # gt_rois_labels: N x R
        # gt_rois_coeffs: N x R x 21*4

        # 3. crop pooling the RoIs
        crops = self.pooling(rois, feature_map) # N x R x C x 7 x 7

        # 4. classification network
        pred_rois_scores, pred_rois_coeffs = self.classification(crops)
        # pred_rois_scores: N x R x 21
        # pred_rois_coeffs: N x R x 21*4
        pred_rois_classes = torch.argmax(pred_rois_scores, dim=2) # N x R

        # 5. calculate classification loss
        rcnn_class_loss, rcnn_bbox_loss = 0, 0
        if self.training:
            # classification loss
            pred_rois_scores = pred_rois_scores.permute(0,2,1)
            rcnn_class_loss = F.cross_entropy(pred_rois_scores, gt_rois_labels)
            # F.cross_entropy() can take multi-dimensional input but only allow class be the 2nd dimension, i.e. input should be N x 21 x R, labels should be N x R

            # bbox regression loss
            rcnn_bbox_loss = F.smooth_l1_loss(pred_rois_coeffs, gt_rois_coeffs)

        # 6. RCNN total loss
        rcnn_loss = rpn_loss + rcnn_class_loss + rcnn_bbox_loss

        return rois, pred_rois_classes, pred_rois_coeffs, rcnn_loss
