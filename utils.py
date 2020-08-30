import matplotlib.pyplot as plt 
import math
import torch
import numpy as np
from torch.utils.tensorboard import SummaryWriter
import os 
import json
voc_classes= {'__background__':0, 'aeroplane':1, 'bicycle':2, 
          'bird':3, 'boat':4, 'bottle':5,'bus':6, 'car':7,
           'cat':8, 'chair':9,'cow':10, 'diningtable':11, 'dog':12,
            'horse':13,'motorbike':14, 'person':15, 'pottedplant':16,
            'sheep':17, 'sofa':18, 'train':19, 'tvmonitor':20}
class Logger(object):
    def __init__(self,log_dir):
        self.log_dir = log_dir
        self.files = {'val':open(os.path.join(log_dir,'val.txt'),'a+'),'train':open(os.path.join(log_dir,'train.txt'),'a+')}
    def write_line2file(self,mode,string):
        self.files[mode].write(string+'\n')
        self.files[mode].flush()
    def write_loss(self,epoch,losses,lr):
        tmp = str(epoch)+'\t'+str(lr)+'\t'
        print('Epoch',':',epoch,'-',lr)
        writer = SummaryWriter(log_dir=self.log_dir)
        writer.add_scalar('lr',math.log(lr),epoch)
        for k in losses:
            if losses[k]>0:            
                writer.add_scalar('Train/'+k,losses[k],epoch)            
                print(k,':',losses[k])
                #self.writer.flush()
        tmp+= str(round(losses['all'],5))+'\t'
        self.write_line2file('train',tmp)
        writer.close()
    def write_metrics(self,epoch,metrics,save=[],mode='Val',log=True):
        tmp =str(epoch)+'\t'
        print("validation epoch:",epoch)
        writer = SummaryWriter(log_dir=self.log_dir)
        for k in metrics:
            if k in save:
                tmp +=str(metrics[k])+'\t'
            if log:
                tag = mode+'/'+k            
                writer.add_scalar(tag,metrics[k],epoch)
                #self.writer.flush()
            print(k,':',metrics[k])
        
        self.write_line2file('val',tmp)
        writer.close()

def iou_wo_center(w1,h1,w2,h2):
    #assuming at the same center
    #return a vector nx1
    inter = torch.min(w1,w2)*torch.min(h1,h2)
    union = w1*h1 + w2*h2 - inter
    ious = inter/union
    ious[ious!=ious] = torch.tensor(0.0) #avoid nans
    return ious
def generalized_iou(bbox1,bbox2):
    #return shape nx1
    bbox1 = bbox1.view(-1,4)
    bbox2 = bbox2.view(-1,4)
    assert bbox1.shape[0]==bbox2.shape[0]
    #tranfer xc,yc,w,h to xmin ymin xmax ymax
    xmin1 = bbox1[:,0] - bbox1[:,2]/2
    xmin2 = bbox2[:,0] - bbox2[:,2]/2
    ymin1 = bbox1[:,1] - bbox1[:,3]/2
    ymin2 = bbox2[:,1] - bbox2[:,3]/2
    xmax1 = bbox1[:,0] + bbox1[:,2]/2
    xmax2 = bbox2[:,0] + bbox2[:,2]/2
    ymax1 = bbox1[:,1] + bbox1[:,3]/2
    ymax2 = bbox2[:,1] + bbox2[:,3]/2

    inter_xmin = torch.max(xmin1,xmin2)
    inter_xmax = torch.min(xmax1,xmax2)
    inter_ymin = torch.max(ymin1,ymin2)
    inter_ymax = torch.min(ymax1,ymax2)
    cover_xmin = torch.min(xmin1,xmin2)
    cover_xmax = torch.max(xmax1,xmax2)
    cover_ymin = torch.min(ymin1,ymin2)
    cover_ymax = torch.max(ymax1,ymax2)

    inter_w = inter_xmax-inter_xmin
    inter_h = inter_ymax-inter_ymin
    mask = ((inter_w>=0 )&( inter_h >=0)).to(torch.float)
    # detect not overlap
    cover = (cover_xmax-cover_xmin)*(cover_ymax-cover_ymin)
    #inter_h[inter_h<0] = 0
    inter = inter_w*inter_h*mask
    #keep iou<0 to avoid gradient diasppear
    area1 = bbox1[:,2]*bbox1[:,3]
    area2 = bbox2[:,2]*bbox2[:,3]
    union = area1+area2 - inter
    ious = inter/union
    gious = iou-(cover-union)/cover
    ious[ious!=ious] = torch.tensor(0.0) #avoid nans
    gous[gous!=gous] = torch.tensor(0.0) #avoid nans
    return ious,gious
def cal_gious_matrix(bbox1,bbox2):
    #return mxn matrix
    bbox1 = bbox1.view(-1,4)
    bbox2 = bbox2.view(-1,4)
    
    #tranfer xc,yc,w,h to xmin ymin xmax ymax
    xmin1 = bbox1[:,0] - bbox1[:,2]/2
    xmin2 = bbox2[:,0] - bbox2[:,2]/2
    ymin1 = bbox1[:,1] - bbox1[:,3]/2
    ymin2 = bbox2[:,1] - bbox2[:,3]/2
    xmax1 = bbox1[:,0] + bbox1[:,2]/2
    xmax2 = bbox2[:,0] + bbox2[:,2]/2
    ymax1 = bbox1[:,1] + bbox1[:,3]/2
    ymax2 = bbox2[:,1] + bbox2[:,3]/2

    inter_xmin = torch.max(xmin1.view(-1,1),xmin2.view(1,-1))
    inter_xmax = torch.min(xmax1.view(-1,1),xmax2.view(1,-1))
    inter_ymin = torch.max(ymin1.view(-1,1),ymin2.view(1,-1))
    inter_ymax = torch.min(ymax1.view(-1,1),ymax2.view(1,-1))
    cover_xmin = torch.min(xmin1.view(-1,1),xmin2.view(1,-1))
    cover_xmax = torch.max(xmax1.view(-1,1),xmax2.view(1,-1))
    cover_ymin = torch.min(ymin1.view(-1,1),ymin2.view(1,-1))
    cover_ymax = torch.max(ymax1.view(-1,1),ymax2.view(1,-1))

    inter_w = inter_xmax-inter_xmin
    inter_h = inter_ymax-inter_ymin
    mask = ((inter_w>=0 )&( inter_h >=0)).to(torch.float)

    # detect not overlap
    cover = (cover_xmax-cover_xmin)*(cover_ymax-cover_ymin)
    #inter_h[inter_h<0] = 0
    inter = inter_w*inter_h*mask
    #keep iou<0 to avoid gradient diasppear
    area1 = bbox1[:,2]*bbox1[:,3]
    area2 = bbox2[:,2]*bbox2[:,3]
    union = area1.view(-1,1)+area2.view(1,-1)
    union -= inter

    ious = inter/union
    gious = iou-(cover-union)/cover
    ious[ious!=ious] = torch.tensor(0.0) #avoid nans
    gous[gous!=gous] = torch.tensor(0.0) #avoid nans 
    return ious,gious
def iou_wt_center(bbox1,bbox2):
    #only for torch, return a vector nx1
    bbox1 = bbox1.view(-1,4)
    bbox2 = bbox2.view(-1,4)
    
    #tranfer xc,yc,w,h to xmin ymin xmax ymax
    xmin1 = bbox1[:,0] - bbox1[:,2]/2
    xmin2 = bbox2[:,0] - bbox2[:,2]/2
    ymin1 = bbox1[:,1] - bbox1[:,3]/2
    ymin2 = bbox2[:,1] - bbox2[:,3]/2
    xmax1 = bbox1[:,0] + bbox1[:,2]/2
    xmax2 = bbox2[:,0] + bbox2[:,2]/2
    ymax1 = bbox1[:,1] + bbox1[:,3]/2
    ymax2 = bbox2[:,1] + bbox2[:,3]/2

    inter_xmin = torch.max(xmin1,xmin2)
    inter_xmax = torch.min(xmax1,xmax2)
    inter_ymin = torch.max(ymin1,ymin2)
    inter_ymax = torch.min(ymax1,ymax2)

    inter_w = inter_xmax-inter_xmin
    inter_h = inter_ymax-inter_ymin
    mask = ((inter_w>=0 )&( inter_h >=0)).to(torch.float)
    
    # detect not overlap
    
    #inter_h[inter_h<0] = 0
    inter = inter_w*inter_h*mask
    #keep iou<0 to avoid gradient diasppear
    area1 = bbox1[:,2]*bbox1[:,3]
    area2 = bbox2[:,2]*bbox2[:,3]
    union = area1+area2 - inter
    ious = inter/union
    ious[ious!=ious] = torch.tensor(0.0)
    return ious
def iou_wt_center_np(bbox1,bbox2):
    #in numpy,only for evaluation,return a matrix m x n
    bbox1 = bbox1.reshape(-1,4)
    bbox2 = bbox2.reshape(-1,4)

    
    #tranfer xc,yc,w,h to xmin ymin xmax ymax
    xmin1 = bbox1[:,0] - bbox1[:,2]/2
    xmin2 = bbox2[:,0] - bbox2[:,2]/2
    ymin1 = bbox1[:,1] - bbox1[:,3]/2
    ymin2 = bbox2[:,1] - bbox2[:,3]/2
    xmax1 = bbox1[:,0] + bbox1[:,2]/2
    xmax2 = bbox2[:,0] + bbox2[:,2]/2
    ymax1 = bbox1[:,1] + bbox1[:,3]/2
    ymax2 = bbox2[:,1] + bbox2[:,3]/2

    #trigger broadcasting
    inter_xmin = np.maximum(xmin1.reshape(-1,1),xmin2.reshape(1,-1))
    inter_xmax = np.minimum(xmax1.reshape(-1,1),xmax2.reshape(1,-1))
    inter_ymin = np.maximum(ymin1.reshape(-1,1),ymin2.reshape(1,-1))
    inter_ymax = np.minimum(ymax1.reshape(-1,1),ymax2.reshape(1,-1))
    
    inter_w = inter_xmax-inter_xmin
    inter_h = inter_ymax-inter_ymin
    mask = ((inter_w>=0 )&( inter_h >=0))
    
    #inter_h[inter_h<0] = 0
    inter = inter_w*inter_h*mask.astype(float)
    inter = (inter_ymax-inter_ymin)*(inter_xmax-inter_xmin)
    area1 = ((ymax1-ymin1+1)*(xmax1-xmin1+1)).reshape(-1,1)
    area2 = ((ymax2-ymin2+1)*(xmax2-xmin2+1)).reshape(1,-1)
    union = area1+area2 - inter
    ious = inter/union
    ious[ious!=ious] = 0
    return ious

def ap_per_class(tp, conf, pred_cls, target_cls):
    """ Compute the average precision, given the recall and precision curves.
    Source: https://github.com/rafaelpadilla/Object-Detection-Metrics.
    # Arguments
        tp:    True positives (list).
        conf:  Objectness value from 0-1 (list).
        pred_cls: Predicted object classes (list).
        target_cls: True object classes (list).
    # Returns
        The average precision as computed in py-faster-rcnn.
    """

    # Sort by objectness
    i = np.argsort(-conf)
    tp, conf, pred_cls = tp[i], conf[i], pred_cls[i]

    # Find unique classes
    unique_classes = np.unique(target_cls)

    # Create Precision-Recall curve and compute AP for each class
    ap, p, r = [], [], []
    for c in tqdm.tqdm(unique_classes, desc="Computing AP"):
        i = pred_cls == c
        n_gt = (target_cls == c).sum()  # Number of ground truth objects
        n_p = i.sum()  # Number of predicted objects

        if n_p == 0 and n_gt == 0:
            continue
        elif n_p == 0 or n_gt == 0:
            ap.append(0)
            r.append(0)
            p.append(0)
        else:
            # Accumulate FPs and TPs
            fpc = (1 - tp[i]).cumsum()
            tpc = (tp[i]).cumsum()

            # Recall
            recall_curve = tpc / (n_gt + 1e-16)
            r.append(recall_curve[-1])

            # Precision
            precision_curve = tpc / (tpc + fpc)
            p.append(precision_curve[-1])

            # AP from recall-precision curve
            ap.append(compute_ap(recall_curve, precision_curve))

    # Compute F1 score (harmonic mean of precision and recall)
    p, r, ap = np.array(p), np.array(r), np.array(ap)
    f1 = 2 * p * r / (p + r + 1e-16)

    return p, r, ap, f1, unique_classes.astype("int32")

def compute_ap(recall, precision):
    """ Compute the average precision, given the recall and precision curves.
    Code originally from https://github.com/rbgirshick/py-faster-rcnn.

    # Arguments
        recall:    The recall curve (list).
        precision: The precision curve (list).
    # Returns
        The average precision as computed in py-faster-rcnn.
    """
    # correct AP calculation
    # first append sentinel values at the end
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([0.0], precision, [0.0]))

    # compute the precision envelope
    for i in range(mpre.size - 1, 0, -1):
        mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

    # to calculate area under PR curve, look for points
    # where X axis (recall) changes value
    i = np.where(mrec[1:] != mrec[:-1])[0]

    # and sum (\Delta recall) * prec
    ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
    return ap

def cal_tp_per_item(pds,gts,threshold=0.5):
    assert (len(pds.shape)>1) and (len(gts.shape)>1)
    n = pds.shape[0]
    tps = np.zeros(n)
    labels = gts[:,0].numpy()
    for c in np.unique(labels):
        mask_pd = pds[:,-1] == c
        pdbboxes = pds[mask_pd,:4].reshape(-1,4)
        gtbboxes = gts[gts[:,0] == c,1:].reshape(-1,4)
        nc = pdbboxes.shape[0]
        mc = gtbboxes.shape[0]
        tpsc = np.zeros(nc)
        selected = np.zeros(mc)
        for i in range(len(nc)):
            if mc == 0:
                break
            pdbbox = pdbboxes[i]
            iou,best = iou_wt_center_np(pdbbox,gtbboxes).max(axis=0)
            if iou >=threshold  and selected[i] !=1:
                selected[best] = 1
                tpsc[i] = 1
        tps[mask_pd][tpsc] = 1
    return [tps,pds[:,-2],pds[:,-1]]    

    

def cal_metrics_wo_cls(pd,gt,threshold=0.5):
    pd = pd.cpu().numpy()#n
    gt = gt.cpu().numpy()#m
    pd_bboxes = pd[:,:4]
    gt = gt[:,1:]
    m = len(gt)
    n = len(pd_bboxes)
    if n>0 and m>0:
        ious = iou_wt_center_np(pd_bboxes,gt) #nxm
        scores = ious.max(axis=1) 
        fp = scores <= threshold

        #only keep trues
        ious = ious[~fp,:]
        fp = fp.sum() # transfer to scalar


        select_ids = ious.argmax(axis=1)
        #discard fps hit gt boxes has been hitted by bboxes with higher conf
        tp = len(np.unique(select_ids))
        fp += len(select_ids)- tp

        
        # groud truth with no associated predicted object
        assert (fp+tp)==n
        fn = m-tp
        p = tp/n
        r = tp/m
        assert(p<=1)
        assert(r<=1)
        ap = tp/(fp+fn+tp)
        return p,r,ap
    elif m>0 or n >0 :
        return 0,0,0
    else:
        return 1,1,1


    
def non_maximum_supression(preds,conf_threshold=0.5,nms_threshold = 0.4):
    preds = preds[preds[:,4]>conf_threshold]
    if len(preds) == 0:
        return preds      
    score = preds[:,4]*preds[:,5:].max(1)[0]
    idx = torch.argsort(score,descending=True)
    preds = preds[idx]
    preds = preds[score[idx] >= conf_threshold]    
    if len(preds) == 0:
        return preds 
    cls_confs,cls_labels = torch.max(preds[:,5:],dim=1,keepdim=True)
    dets = torch.cat((preds[:,:4],preds[:,4]*cls_confs.float(),cls_labels.float()),dim=1)
    keep = []
    while len(dets)>0:
        mask = dets[0,-1]==dets[:,-1]
        new = dets[0]
        keep.append(new)
        ious = iou_wt_center(dets[0,:4],dets[:,:4])
        if not(ious[0]>=0.7):
            ious[0] = 1
        mask = mask & (ious>nms_threshold)
        #hard-nms        
        dets = dets[~mask]
    return torch.stack(keep).reshape(-1,6)
def non_maximum_supression_soft(preds,conf_threshold=0.5,nms_threshold=0.4):
    keep = []
    cls_confs,cls_labels = torch.max(preds[:,5:],dim=1,keepdim=True)
    dets = torch.cat((preds[:,:4],preds[:,4]*cls_confs.float(),cls_labels.float()),dim=1)
    dets = dets[dets[:,4]>conf_threshold]
    while len(dets)>0:
        _,idx = torch.max(dets[:,4]*dets[:,5],dim=0)
        val = dets[:,4]        
        pd = dets[idx]
        dets = torch.cat((dets[:idx],dets[idx+1:]))
        ious = iou_wt_center(pd[:4],dets[:,:4])
        mask = (ious>nms_threshold) & (pd[-1]==dets[:,-1])
        keep.append(pd)
        dets[mask,4] *= (1-ious[mask])*(1-val)
        dets = dets[dets[:,4]>conf_threshold]
    return torch.stack(keep).reshape(-1,6)













