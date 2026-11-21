import unittest
import numpy as np
import pandas as pd
from src.decision import review,range_validation
from src.analysis import b76,RISK_FREE

class StrategySelection(unittest.TestCase):
    def run_view(self, view):
        windows=dict(vix=np.full(400,18.),up=np.linspace(0,.01,400),
                     dn=np.linspace(0,.01,400),end=np.linspace(-.01,.01,400))
        def chain(t):
            info=dict(spot=25000,F=25000,lot=65,Tm=t)
            k=np.arange(23800,26201,50)
            ch=pd.DataFrame(index=k)
            for cp in ("CE","PE"):
                col=cp.lower()
                ch[col+"_px"]=[b76(25000,x,t,.18,RISK_FREE,cp) for x in k]
                for field,val in (("iv",.18),("vol",10),("oi",50)):
                    ch[col+"_"+field]=val
            return ch,info
        near,n=chain(.02);far,f=chain(.04)
        return review(near,far,n,f,dict(spot=25000,lot=65,sd_move=220),
                      dict(vix=18,pctile=20,chg5_pct=0),dict(atr=200),view,windows,windows,None)
    def test_single_side(self):
        for view,name in (("Bullish","Single put calendar"),("Bearish","Single call calendar")):
            r=self.run_view(view)
            self.assertEqual(set(r["picks"]),{name})
            self.assertIn("Sell 1",r["picks"][name]["legs"])
            self.assertTrue(r["reasons"])
    def test_mild(self):
        for view in ("Mildly bullish","Mildly bearish","Neutral / range"):
            r=self.run_view(view)
            self.assertIn("Iron condor",r["picks"])
            self.assertIn("Sell 2",r["picks"]["2:1 double calendar"]["legs"])
            self.assertGreater(r["validation"][1],0)
    def test_missing_history(self):
        self.assertIsNone(range_validation(None))
