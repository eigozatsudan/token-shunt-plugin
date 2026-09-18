import random
from math import comb

def fisher_p(a,b,c,d):
    # two-sided Fisher exact on [[a,b],[c,d]]
    n=a+b+c+d; r1=a+b; c1=a+c
    def pr(x):
        return comb(r1,x)*comb(n-r1,c1-x)/comb(n,c1)
    p0=pr(a); tot=0.0
    lo=max(0,c1-(n-r1)); hi=min(r1,c1)
    for x in range(lo,hi+1):
        px=pr(x)
        if px<=p0*(1+1e-9): tot+=px
    return min(1.0,tot)

rng=random.Random(20260918)
for n in (30,35,40,45):
    for (p_bare,p_plan) in ((0.30,0.05),(0.22,0.05),(0.30,0.10),(0.22,0.10)):
        hit=0; T=4000
        for _ in range(T):
            a=sum(rng.random()<p_bare for _ in range(n))
            c=sum(rng.random()<p_plan for _ in range(n))
            if fisher_p(a,n-a,c,n-c)<0.05: hit+=1
        print(f"n={n:3d}/arm  bare={p_bare:.2f} plan={p_plan:.2f}  power={hit/T:.2f}")
    print()
