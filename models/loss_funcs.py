import torch.nn as nn
import torch
import numpy as np

from .utils import iou_wo_center,generalized_iou
#Functional Utils
mse_loss = nn.MSELoss()
bce_loss = nn.BCELoss()
def dice_loss1d(pd,gt,threshold=0.5):
    assert pd.shape == gt.shape
    if gt.shape[0]==0:
        return 0
    inter = torch.sum(pd*gt)
    pd_area = torch.sum(torch.pow(pd,2))
    gt_area = torch.sum(torch.pow(gt,2))
    dice = (2*inter+1)/(pd_area+gt_area+1)
    #fix nans
    dice[dice != dice] = dice.new_tensor([1.0])
    return 1-dice.mean()
def dice_loss(pd,gt,threshold=0.5):
    dims = tuple(range(len(pd.shape)))
    inter = torch.sum(pd*gt,dim=dims)
    pd_area = torch.sum(torch.pow(pd,2),dim=dims)
    gt_area = torch.sum(torch.pow(gt,2),dim=dims)
    dice = (2*inter+1)/(pd_area+gt_area+1)
    #fix nans
    dice[dice != dice] = dice.new_tensor([1.0])
    return 1-dice.mean()

def make_grid_mesh(grid_size,device='cuda'):
    x = np.arange(0,grid_size,1)
    y = np.arange(0,grid_size,1)
    grid_x,grid_y = np.meshgrid(x,y)
    grid_x = torch.tensor(grid_x).view(1,1,grid_size,grid_size).to(dtype=torch.float,device=device)
    grid_y = torch.tensor(grid_y).view(1,1,grid_size,grid_size).to(dtype=torch.float,device=device)
    return grid_x,grid_y
def make_grid_mesh_xy(grid_size,device='cuda'):
    x = np.arange(0,grid_size[1],1)
    y = np.arange(0,grid_size[0],1)
    grid_x,grid_y = np.meshgrid(x,y)
    grid_x = torch.tensor(grid_x).to(dtype=torch.float,device=device)
    grid_y = torch.tensor(grid_y).to(dtype=torch.float,device=device)
    return grid_x,grid_y


### Anchor based
class YOLOLoss(nn.Module):
    def __init__(self,cfg=None):
        super(YOLOLoss,self).__init__()
        self.object_scale = cfg.obj_scale
        self.noobject_scale = cfg.noobj_scale
        self.cls_num = cfg.cls_num
        self.ignore_threshold = cfg.ignore_threshold
        self.device= 'cuda'
        self.target_num = 120
        anchors = [cfg.anchors[i] for i in cfg.anchor_ind]
        self.num_anchors = len(anchors)
        self.anchors = np.array(anchors).reshape(-1,2)
        self.channel_num = self.num_anchors*(self.cls_num+5)
        self.match_threshold = cfg.match_threshold
        self.cls_scale = cfg.cls_scale
    def build_target(self,pds,gts):
        self.device ='cuda' if pds.is_cuda else 'cpu'
        nB,nA,nH,nW,_ = pds.shape
        assert nH==nW
        nC = self.cls_num
        #threshold = th
        nGts = len(gts)
        obj_mask = torch.zeros(nB,nA,nH,nW,dtype=torch.bool,device=self.device)
        noobj_mask = torch.ones(nB,nA,nH,nW,dtype=torch.bool,device=self.device)
        tbboxes = torch.zeros(nB,nA,nH,nW,4,dtype=torch.float,device=self.device)  
        tcls = torch.zeros(nB,nA,nH,nW,nC,dtype=torch.float,device=self.device) 
        if nGts==0:
            return obj_mask,noobj_mask,tbboxes,tcls,obj_mask.float()
        #convert target
        gt_boxes = gts[:,2:6]*nH
        gws = gt_boxes[:,2]
        ghs = gt_boxes[:,3]

        ious = torch.stack([iou_wo_center(gws,ghs,w,h) for (w,h) in self.scaled_anchors])
        vals, best_n = ious.max(0)
        ind = torch.argsort(vals)
        # so that obj with bigger iou will cover the smaller one 
        # useful for crowed scenes
        idx = torch.argsort(gts[ind,-1],descending=True)#sort as match num,then gt has not matched will be matched first
        ind = ind[idx]
        ind = ind[(vals[ind]>self.match_threshold)|(gts[ind,-1]==0)]
        #discard the gts below the match threshold and has been matched


        best_n =best_n[ind]
        batch = gts[ind,0].long()
        labels = gts[ind,1].long()
        gxs,gys = gt_boxes[ind,0],gt_boxes[ind,1]
        gis,gjs = gxs.long(),gys.long()
        #calculate bbox ious with anchors      
        obj_mask[batch,best_n,gjs,gis] = 1
        noobj_mask[batch,best_n,gjs,gis] = 0
        selected = torch.zeros_like(obj_mask,dtype=torch.long).fill_(-1)
        
        tbboxes[batch,best_n,gjs,gis] = gt_boxes[ind,:]
        tcls[batch,best_n,gjs,gis,labels] = 1
        selected[batch,best_n,gjs,gis] = ind
        ious = ious.t()[ind]
        #ignore big overlap but not the best
        for i,iou in enumerate(ious):
            noobj_mask[batch[i],iou > self.ignore_threshold,gjs[i],gis[i]] = 0

        
        selected = torch.unique(selected[selected>=0])
        gts[selected,-1] += 1 #marked as matched

        
        return obj_mask,noobj_mask,tbboxes,tcls,obj_mask.float()
    
    def get_pds_and_targets(self,pred,infer=False,gts=None):
        grid_x,grid_y = make_grid_mesh_xy(self.grid_size,self.device)
        xs = torch.sigmoid(pred[...,0])#dxs
        ys = torch.sigmoid(pred[...,1])#dys
        ws = pred[...,2]
        hs = pred[...,3]
        conf = torch.sigmoid(pred[...,4])#Object score
        cls_score = torch.sigmoid(pred[...,5:])
        #grid,anchors
        

        pd_bboxes = torch.zeros_like(pred[...,:4],dtype=torch.float,device=self.device)
        pd_bboxes[...,0] = xs + grid_x
        pd_bboxes[...,1] = ys + grid_y
        pd_bboxes[...,2] = torch.exp(ws)*self.anchors_w
        pd_bboxes[...,3] = torch.exp(hs)*self.anchors_h
        nb = pred.shape[0]        
        if infer:
            pd_bboxes[...,[0,2]]/=self.grid_size[1]
            pd_bboxes[...,[1,3]]/=self.grid_size[0]     
            return torch.cat((pd_bboxes.view(nb,-1,4),conf.view(nb,-1,1),cls_score.view(nb,-1,self.cls_num)),dim=-1)
        else:
            pds_bbox = (xs,ys,ws,hs,pd_bboxes)
            obj_mask,noobj_mask,tbboxes,tcls,tconf = self.build_target(pd_bboxes,gts)
            tobj = (noobj_mask,tconf)
            return (pds_bbox,conf,cls_score),obj_mask,tbboxes,tobj,tcls
    
    def cal_bbox_loss(self,pds,tbboxes,obj_mask,res):
        xs,ys,ws,hs,_= pds
        txs,tys,tws,ths = tbboxes.permute(4,0,1,2,3).contiguous()
        tws /= self.anchors_w
        ths /= self.anchors_h
        loss_x = mse_loss(xs[obj_mask],txs[obj_mask]-txs[obj_mask].floor())
        loss_y = mse_loss(ys[obj_mask],tys[obj_mask]-tys[obj_mask].floor())
        loss_xy = loss_x + loss_y

        loss_w = mse_loss(ws[obj_mask],torch.log(tws[obj_mask]+1e-16))
        loss_h = mse_loss(hs[obj_mask],torch.log(ths[obj_mask]+1e-16))
        loss_wh = loss_w + loss_h
        res['wh']=loss_wh.item()
        res['xy']=loss_xy.item()
        loss_bbox = loss_xy+loss_wh #mse_loss(pd_bboxes[obj_mask],tbboxes[obj_mask])
        if torch.isnan(loss_bbox):
            print("why??????????")
            exit()
        return loss_bbox,res
    
    def cal_cls_loss(self,pds,target,obj_mask,res):
        loss_cls = bce_loss(pds[obj_mask],target[obj_mask])
        res['cls'] = loss_cls.item()
        return loss_cls,res
    
    def cal_obj_loss(self,pds,target,obj_mask,res):
        noobj_mask,tconf = target
        loss_conf_obj = self.object_scale*bce_loss(pds[obj_mask],tconf[obj_mask])
        loss_conf_noobj = self.noobject_scale*bce_loss(pds[noobj_mask],tconf[noobj_mask])
        loss_conf = loss_conf_noobj+loss_conf_obj
        res['obj'] = loss_conf_obj.item()
        res['conf'] = loss_conf.item()
        return loss_conf,res
    
    def forward(self,out,gts=None,size=None,infer=False):
        nb,_,nh,nw = out.shape
        self.device ='cuda' if out.is_cuda else 'cpu'
        self.grid_size = (nh,nw)
        self.stride = (size[0]/nh,size[1]/nw)
        pred = out.view(nb,self.num_anchors,self.cls_num+5,nh,nw).permute(0,1,3,4,2).contiguous()
        #reshape to nB,nA,nH,nW,bboxes
        self.scaled_anchors = torch.tensor([(a_w / self.stride[1], a_h / self.stride[0]) for a_w, a_h in self.anchors],dtype=torch.float,device=self.device)
        self.anchors_w = (self.scaled_anchors[:,0]).reshape((1, self.num_anchors, 1, 1))
        self.anchors_h = (self.scaled_anchors[:,1]).reshape((1, self.num_anchors, 1, 1))       
        
        if infer:
            return self.get_pds_and_targets(pred,infer)
        else:
            pds,obj_mask,tbboxes,tobj,tcls = self.get_pds_and_targets(pred,infer,gts)
        pds_bbox,pds_obj,pds_cls = pds
        loss_obj,res = self.cal_obj_loss(pds_obj,tobj,obj_mask,{})                     
        if obj_mask.float().max()==1:
            loss_reg,res = self.cal_bbox_loss(pds_bbox,tbboxes,obj_mask,res)
            loss_cls,res = self.cal_cls_loss(pds_cls,tcls,obj_mask,res)
            total = loss_reg+loss_obj+self.cls_scale*loss_cls
        else:
            total = loss_obj
        res['all'] = total.item()
        return res,total
class YOLOLoss_iou(YOLOLoss):
    def cal_bbox_loss(self,pds,tbboxes,obj_mask,res):
        pd_bboxes = pds[-1]
        if obj_mask.float().max()>0:#avoid no gt_objs
            ious,gous = generalized_iou(pd_bboxes[obj_mask],tbboxes[obj_mask])
            loss_iou = 1 - ious.mean()
            loss_gou = 1 - gous.mean()
        else:
            loss_iou = torch.tensor(0.0,dtype=torch.float,device=self.device)
            loss_gou = torch.tensor(0.0,dtype=torch.float,device=self.device)
        res['iou'] = loss_iou.item()
        res['gou'] = loss_gou.item()
        return loss_iou,res
class YOLOLoss_gou(YOLOLoss):
    def cal_bbox_loss(self,pds,tbboxes,obj_mask,res):
        pd_bboxes = pds[-1]
        if obj_mask.float().max()>0:#avoid no gt_objs
            ious,gous = generalized_iou(pd_bboxes[obj_mask],tbboxes[obj_mask])
            loss_iou = 1 - ious.mean()
            loss_gou = 1 - gous.mean()
        else:
            loss_iou = torch.tensor(0.0,dtype=torch.float,device=self.device)
            loss_gou = torch.tensor(0.0,dtype=torch.float,device=self.device)
        res['iou'] = loss_iou.item()
        res['gou'] = loss_gou.item()
        return loss_gou,res
class YOLOLoss_com(YOLOLoss):
    def cal_bbox_loss(self,pds,tbboxes,obj_mask,res):
        xs,ys,ws,hs,pd_bboxes = pds
        txs,tys,tws,ths = tbboxes.permute(4,0,1,2,3).contiguous()
        tws /= self.anchors_w
        ths /= self.anchors_h
        loss_x = mse_loss(xs[obj_mask],txs[obj_mask]-txs[obj_mask].floor())
        loss_y = mse_loss(ys[obj_mask],tys[obj_mask]-tys[obj_mask].floor())
        loss_xy = loss_x + loss_y
        loss_wh = loss_w + loss_h
        res['wh']=loss_wh.item()
        res['xy']=loss_xy.item()
        loss_bbox = loss_xy+loss_wh 
        if torch.isnan(loss_bbox):
            exit()
        if obj_mask.float().max()>0:#avoid no gt_objs
            ious,gous = generalized_iou(pd_bboxes[obj_mask],tbboxes[obj_mask])
            loss_iou = 1 - ious.mean()
            loss_gou = 1 - gous.mean()
        else:
            loss_iou = torch.tensor(0.0,dtype=torch.float,device=self.device)
            loss_gou = torch.tensor(0.0,dtype=torch.float,device=self.device)
        res['iou'] = loss_iou.item()
        res['gou'] = loss_gou.item()
        return loss_gou+loss_bbox,res

class LossAPI(nn.Module):
    def __init__(self,cfg,loss):
        super(LossAPI,self).__init__()
        self.bbox_losses = cfg.anchor_divide.copy()
        self.not_match = 0
        for i,ind in enumerate(cfg.anchor_divide):
            cfg.anchor_ind = ind
            self.bbox_losses[i] = Losses[loss](cfg)
    def forward(self,outs,gt=None,size=None,infer=False):
        if infer:
            res = []
            for out,loss in zip(outs,self.bbox_losses):
                result = loss(out,gt,size,infer=True)
                res.append(result)
            return torch.cat(res,dim=1)
        else:
            res ={'xy':0.0,'wh':0.0,'conf':0.0,'cls':0.0,'obj':0.0,'all':0.0,'iou':0.0,'gou':0.0}
            totals = []
            match =torch.zeros((gt.shape[0],1),dtype=torch.float,device=gt.device)
            gt = torch.cat((gt,match),-1)
            for out,loss in zip(outs,self.bbox_losses): 
               ret,total = loss(out,gt,size)
               for k in ret:
                   res[k] +=ret[k]
               totals.append(total)
            not_match = int((gt[:,-1]==0).sum())
            if not_match>0:
                self.not_match += not_match
            return res,torch.stack(totals).sum()
    def reset_notmatch(self):
        self.not_match = 0
Losses = {'yolo':YOLOLoss,'yolo_iou':YOLOLoss_iou,'yolo_gou':YOLOLoss_gou,'yolo_com':YOLOLoss_com}



        







        