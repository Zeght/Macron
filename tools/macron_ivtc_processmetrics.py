import sys
import os
import re
import copy
import math
from collections import deque

certainity = ["improbably", "unlikely", "uncertainly", "plausibly",
              "possibly", "feasibly", "likely", "seemingly",
              "apparently", "definitely"]

class Frameinfo:
    def __init__(self, match, mics):
        self.match = match
        self.mics = mics
    
    def __repr__(self):
        return str((self.match, self.mics))

class Range:
    def __init__(self, l, r, match=None):
        self.l = l
        self.r = r
        self.match = match
    
    def __len__(self):
        return max(self.r - self.l, 0)

    def __repr__(self):
        return str(((self.l, self.r), self.match))
    
    def key(self):
        return (self.l, -self.r, self.match)
    
    @classmethod
    def Fromseg(cls, clip, l, r):
        if l==r:
            return None
        return cls(l, r, findpattern(clip, l, r)[0])
    def shift(self, delta):
        self.l += delta
        self.r += delta


class Clipinfo:
    def __init__(self, frames=None, ranges=None, cyclelen=None, chunklen=None):
        self.frames = frames
        self.lastframe = len(frames)-1
        self.ranges = ranges
        self.cyclelen = cyclelen
        self.chunklen = chunklen

def zerometricslist(length):
    return [[0,0,0] for i in xrange(0, length)]

def overlap(a, b):
    return min(a.r , b.r) - max(a.l, b.l)

def matchnumtoletter(match):
    matchletter = {0:"p", 1:"c", 2:"n", -2:"u", -1:"b"}
    if match not in matchletter:
        raise KeyError("unknown match '%d'" % match)
    else:
        return matchletter.get(match)

def matchlettertonum(match):
    matchnum = {"p":0, "c":1, "n":2, "u":-2, "b":-1}
    if match not in matchnum:
        raise KeyError("unknown match '%s'" % match)
    else:
        return matchnum.get(match)

def micfrommatch(clip, index, match):
    if type(match) is str:
        match = matchlettertonum(match)
    if match>=0:
        return clip.frames[index].mics[match]
    elif match=="u":    #oposite field + next frame field
        return clip.frames[index+1].mics[0]
    else:               #"b", oposite field + previous frame field
        return clip.frames[index-1].mics[2]

def readmetrics(metricsfilelist, suffix=""):
    if type(metricsfilelist)!=list:
        metricsfilelist = [metricsfilelist]
    regexp = re.compile("(?P<fnum>[0-9]*) (?P<match>[pcnbu]) (?P<combed>\- )?"
                                + "(?P<matchmic>\[[0-9]*\]) \((?P<mics>.*)\)")
    framelist = []
    blank = Frameinfo("c", [0]*3)
    for metricsfile in metricsfilelist:
        filename = (suffix+".").join(metricsfile.rsplit(".", 1))
        with open(filename, "r") as metrics:
            for metric in metrics:
                info = regexp.match(metric)
                if info==None: continue
                fnum = int(info.group("fnum"))
                match = info.group("match")
                mics = map(int, info.group("mics").split())
                frame = Frameinfo(match, mics)
                if ((len(framelist)>fnum) and (framelist[fnum]!=blank) and (str(frame)!=str(framelist[fnum]))):
                    message("WARNING: conflicting data for frame %d" % (fnum))
                while (len(framelist)<=fnum):
                    framelist.append(blank)
                framelist[fnum] = frame
    return framelist

def appendtorangelist(rangelist, point, extraprop=None):
    if (len(rangelist)==0 or rangelist[-1].r<point
      or (extraprop and extraprop!=rangelist[-1].match)):
        if extraprop!=None:
            rangelist.append(Range(point, point + 1, extraprop))
        else:
            rangelist.append(Range(point, point + 1))
    else:
        rangelist[-1].r+=1
        if (rangelist[-1].match==None and extraprop):
            rangelist[-1].match = extraprop

def weightmatch(matchmic):
    #mesure of match being bad, p and n is penalised a bit
    match, mic = matchmic
    penalty = 1.5
    return mic + (penalty if match!=1 else 0)

def findpattern(clip, l, r, quick=False):
    #cyclepos is position in cycle in [0..cyclepos] range
    #compute sum of mic for each cyclepos for all matches
    allsum = 0
    micsum = zerometricslist(clip.cyclelen)
    for i in xrange(l, min(r, clip.lastframe + 1)):
        cyclepos = i % clip.cyclelen
        for j in xrange(0,3):
            micsum[cyclepos][j] += clip.frames[i].mics[j]
            allsum += clip.frames[i].mics[j]
    #for every cyclepos choose best match (by lowest micsum)
    pattern = ""
    for mics in micsum:
        mn = min(enumerate(mics), key=weightmatch)
        pattern += matchnumtoletter(mn[0])
    if not quick:
        patpat = pattern*2
        ccccp = "c"*(clip.cyclelen-1)+"p"
        if (ccccp  in patpat):
            c = (pattern.find("pc")+1) % clip.cyclelen
            diff = micsum[c][0] - micsum[c][1]
            if diff==0:
                pattern = pattern[:c]+"p"+pattern[c+1:]
    return (pattern, allsum)

def processchunks(clip):
    chunkpatterns = []
    curfinfo = 0
    lastframe = len(clip.frames)-1
    r=0
    #compute chunk metrics and get patterns
    for i in xrange(0, (lastframe+clip.chunklen-1)/clip.chunklen):
        (pattern, micsum) = findpattern(clip, i*clip.chunklen, (i+1)*clip.chunklen, quick=True)
        chunkpatterns.append(Frameinfo(pattern, micsum))
    return chunkpatterns

def makeranges(clip):
    chunkpatterns = processchunks(clip)
    clip.ranges = []
    for i, chunk in enumerate(chunkpatterns):
        appendtorangelist(clip.ranges, i,
                          extraprop=(chunk.match if (chunk.mics>0) else None))
    for range in clip.ranges:
        range.l *= clip.chunklen
        range.r *= clip.chunklen
    clip.ranges[-1].r = min(clip.ranges[-1].r, clip.lastframe + 1)
    if clip.ranges[-1].match == None:
        clip.ranges[-1].match = "c"*clip.cyclelen
    if clip.ranges[0].match == None:
        clip.ranges[0].match = "c"*clip.cyclelen

def isgoodpattern(pat, num=False):
    cccpp = ("c"*(len(pat)-2)) + "pp"
    cccnn = ("c"*(len(pat)-2)) + "nn"
    ccccc = ("c"*(len(pat)))
    patpat = pat+pat
    if not num:
        return cccpp in patpat or cccnn in patpat or ccccc in patpat
    else:
        if ccccc in patpat or cccnn in patpat:
            return 1
        elif cccpp in patpat:
            return 2
        else:
            return 0

def mergeable(a, b):
    if type(a)!=str:
        return (a==b)
    aa = a*2
    bb = b*2
    ppccc = "pp" + ("c"*(len(a)-2))
    pp = aa.find(ppccc)
    #a[pp] will be dropped so we can have any other match there
    return (a==b) or (b[:pp]+"p"+b[pp+1:] == a)

def ranges_merge(clip, thr=0):
    #merging clip.ranges with same pattern
    if type(clip)==list:
        clip = Clipinfo([0], clip, None, None)
        nonclip = True
    else:
        nonclip = False
    delete = [False] * len(clip.ranges)
    merged = False
    for i, range in enumerate(clip.ranges):
        if delete[i]: continue
        j = i+1
        while j<len(clip.ranges) and clip.ranges[j].l<=range.r+thr:
            if (mergeable(range.match, clip.ranges[j].match)):
                range.r = max(range.r, clip.ranges[j].r)
                delete[j] = True
                merged = True
            elif (mergeable(clip.ranges[j].match, range.match)):
                range.r = max(range.r, clip.ranges[j].r)
                delete[j] = True
                merged = True
                range.match = clip.ranges[j].match
            j+=1
    if merged:
        clip.ranges = [range for d, range in zip(delete, clip.ranges) if not d]
    return merged

def processranges_good(clip):
    INF = 2000000000
    penalty = 120
    cost = []
    prev = []
    patterns_num = 3**clip.cyclelen
    patternweights = []
    for ii in xrange(patterns_num):
        pattern = ""
        for d in xrange(clip.cyclelen):
            if (ii % 3 == 0):
                pattern+="p"
            elif (ii % 3 == 1):
                pattern+="c"
            else:
                pattern+="n"
            ii/=3
        patternweights.append(isgoodpattern(pattern, num=True))
    
    for i in xrange(len(clip.frames)):
        cost.append([])
        prev.append([])
        cyclepos = i % clip.cyclelen
        pow3 = 3**cyclepos
        if i==0:
            for match in xrange(patterns_num):
                mic = clip.frames[i].mics[match / pow3 % 3] * 4
                cost[i].append(mic)
                prev[i].append(0)
        else:
            for match in xrange(patterns_num):
                mic = clip.frames[i].mics[match / pow3 % 3] * 4
                if cost[i-1][mnmatch] + penalty <= cost[i-1][match] :
                    cost[i].append(cost[i-1][mnmatch] + mic + penalty - patternweights[match])
                    prev[i].append(mnmatch)
                else:
                    cost[i].append(cost[i-1][match] + mic - patternweights[match])
                    prev[i].append(match)
                    
        mnmic = INF
        for match, mic in enumerate(cost[i]):
            if mnmic > mic:
                mnmic = mic
                mnmatch = match
    mn = INF
    for i, mic in enumerate(cost[-1]):
        if mn > mic:
            mn = mic
            mnmatch = i
    revmatches = []
    i = len(cost)-1
    while (i>=0):
        revmatches.append(mnmatch)
        mnmatch = prev[i][mnmatch]
        i-=1
    matches = []
    for i, match in enumerate(reversed(revmatches)):
        appendtorangelist(matches, i, match)
        
    for i in xrange(len(matches)):
        ternary = matches[i].match
        match = ""
        for ii in xrange(clip.cyclelen):
            match += matchnumtoletter(ternary % 3)
            ternary /= 3
        matches[i].match = match
    
    clip.ranges = matches

def mergetilemetrics(metrics, bord=False):
    metrics[""] =  copy.deepcopy(metrics["_tile0"])
    for suffix in metrics:
        if bord or ("tile" in suffix):
            for i in xrange(len(metrics[""])):
                for j in xrange(3):
                    metrics[""][i].mics[j] = max(metrics[""][i].mics[j],
                                                 metrics[suffix][i].mics[j])

def removeuselessmetrics(oclip, metrics):
    clip = Clipinfo(frames=metrics, ranges=oclip.ranges, cyclelen=oclip.cyclelen)
    winsize = clip.cyclelen*2
    winmics = deque()
    winmedsum = 0
    winlowsum = 0
    winsumdiff = 0
    rangenum = 0
    sub = [0]*len(metrics)
    for i, frame in enumerate(clip.frames):
        while rangenum < len(clip.ranges) and clip.ranges[rangenum].r<=i:
            rangenum+=1
        if (rangenum >= len(clip.ranges)): break
        cyclepos = i % clip.cyclelen
        range = clip.ranges[rangenum]
        match = range.match[cyclepos]
        mic = micfrommatch(clip, i, match)
        winmics.append(mic)
        if i>=winsize:
            micslist = list(winmics)
            micslist.sort()
            winmedsum = sum(micslist[winsize/3 : winsize/3*2])
            winlowsum = sum(micslist[0 : winsize/3])
            winsumdiff = winmedsum-winlowsum
            if (winsumdiff<winlowsum*3):
                sub[i-winsize/2] = (winlowsum-winsumdiff/3)/(winsize/3)
            winmics.popleft()
    subavg = []
    window = deque()
    wsum = 0
    for i in xrange(len(sub)):
        window.append(max(sub[max(0, i-winsize/2):min(i+winsize/2, len(sub))]))
        wsum+=window[-1]
        if len(window)>winsize:
            wsum-=window.popleft()
        if (i>winsize/2):
            for j in xrange(3):
                metrics[i-winsize/2].mics[j] = max(0, metrics[i-winsize/2].mics[j]-wsum/winsize)

def filtermixcontentranges(mix60i, mix30p):
    mix = []
    for range in mix60i:
        if isgoodpattern(range.match, num=True)==2 and len(range)>4:
            range.match = (range.match*2).find("cp")
            #ivtc60itxt requires index of cp
            mix.append(range)
    for range in mix30p:
        if isgoodpattern(range.match, num=True)==2 and len(range)>4:
            range.match = (range.match*2).find("cp") + len(range.match)
            #ranges for ivtc30p will have match>=cyclelen
            mix.append(range)
    return mix

def mergeborder(clip, finfo):
    #merge metrics from top/bottom, check for inconsistencies
    #use p-match mics to detect 30p on top of 24t, c-match for 60i
    mic_p = 0
    micbord_p = 0
    mix60i = []
    mix30p = []
    mic_c = 0
    micbord_c = 0
    #compute sum of mics difference between bottom and middle part of frame
    #append if sum in window is larger than thr
    winsize = clip.cyclelen*2
    winmics = deque()
    thr = 50
    rangenum = 0
    currange = clip.ranges[0]
    lastignore = -100
    clip2 = Clipinfo(finfo, clip.ranges, None, clip.cyclelen)
    for i, frame in enumerate(clip.frames):
        while (rangenum < (len(clip.ranges)-1) and clip.ranges[rangenum].r<=i):
            rangenum+=1
            currange = clip.ranges[rangenum]
        cyclepos = i % clip.cyclelen
        match = currange.match[cyclepos]
        mic = micfrommatch(clip, i, match)
        micbord = micfrommatch(clip2, i, match)
        
        if ( micbord>mic+20 
          and i>lastignore + 30
          and ( match=="c" and mic_c>=micbord_c+2 and micfrommatch(clip, i, "p")<mic+2
             or match=="p" and mic_p>=micbord_p+2 and micfrommatch(clip, i, "c")<mic+2)):
            mic = micbord #single-frame outliers that don't break the match are ok
            lastignore = i
        
        if match == "c":
            #60i should look very bad on n matches, micbord_c is reduced if it doesn't
            if (micfrommatch(clip2, i, "n")<(255+micbord*2)/3):
                micbord = (mic*2+micbord)/3
            mic_c += mic
            micbord_c += micbord
            winmics.append(("c", mic, micbord))
        else:
            mic_p += mic
            micbord_p += micbord
            winmics.append(("p", mic, micbord))
        
        if (i<winsize): continue
        
        #c-matches on border should be bad and much worse than in center of frame to consider it 60i
        if (micbord_c>=thr*1.3) and (mic_c*9<=micbord_c):
            appendtorangelist(mix60i, i - winsize/2, clip.ranges[rangenum].match)
        #p-matches on border should be bad and much worse than in center of frame to consider it 30p
        #c-matches souldn't be much worse than p-matches, though
        elif (micbord_p>=thr) and (mic_p*7<=micbord_p) and ((micbord_p-mic_p) > (micbord_c-mic_c)*2):
            appendtorangelist(mix30p, i - winsize/2, clip.ranges[rangenum].match)
        
        #shift window
        lmic = winmics.popleft()
        if lmic[0] == "c":
            mic_c -= lmic[1]
            micbord_c -= lmic[2]
        else:
            mic_p -= lmic[1]
            micbord_p -= lmic[2]
    
    for range in mix30p+mix60i:
        for fnum in xrange(range.l, min(clip.lastframe, range.r)):
            for i in xrange(0, 3):
                finfo[fnum].mics[i] = 0
    return filtermixcontentranges(mix60i, mix30p)

def merge_t_b_chroma(clip, finfo_t, finfo_b, finfo_cr):
    mix = (mergeborder(clip, finfo_t), mergeborder(clip, finfo_b))
    processranges_good(clip)
    for i, frame in enumerate(clip.frames):
        for m in xrange(0, 3):
            finfo_cr[i].mics[m]/=2
            frame.mics[m] = max(frame.mics[m], finfo_cr[i].mics[m])
    return mix

def getfieldtimestamps(pat):
    time=0
    stamps = []
    for i, m in enumerate(pat*2):
        if i<5: continue
        stamps.append((time-1) if (m=="p") else time)
        stamps.append(time)

def decimate_two_patterns(pat1, pat2):
    time1 = getfieldtimestamps(pat1)
    time2 = getfieldtimestamps(pat2)

def find60icrossfades(clip):
    maxfadelen = 15
    testlen = 10
    cf_ranges = []
    thr = 1.5
    for i, range in enumerate(clip.ranges):
        if len(range)<2*maxfadelen or not isgoodpattern(range): continue
        j = i+1
        while j<len(clip.ranges) and len(clip.ranges[j])<2*maxfadelen and clip.ranges[j].l-range.r<=maxfadelen:
            j+=1
        if (j<len(clip.ranges) and len(clip.ranges[j])>2*maxfadelen
           and clip.ranges[j].l-range.r<=maxfadele and isgoodpattern(clip.ranges[j])):
            testrange = Range(range.r-2*testlen, range.r-testlen, range.match)
            llweight = weightrange(clip, testrange, median=True)
            testrange.shift(testlen)
            lweight = weightrange(clip, testrange, median=True)
            testrange.shift(testlen)
            testrange.match = clip.ranges[j].match
            rweight = weightrange(clip, testrange, median=True)
            testrange.shift(testlen)
            rrweight = weightrange(clip, testrange, median=True)
            if (rweight*thr>rrweight or lweight*thr>llweight):
                while (rrweight*1.1>rrweight) and (testrange.r+testlen<=clip.lastframe):
                    testrange.shift(testlen)
                    rweight = rrweight
                    rrweight = weightrange(clip, testrange, median=True)
                rbound = testrange.l
                testrange = Range(range.r-2*testlen, range.r-testlen, range.match)
                while (llweight*1.1>lweight) and (testrange.l-testlen>0):
                    testrange.shift(-testlen)
                    lweight = llweight
                    llweight = weightrange(clip, testrange, median=True)
                lbound = testrange.r
                cf_ranges.append(((lbound, rbound),
                                decimate_two_patterns(range.match, clip.ranges[j].match)))

def PP(clip, cleanmetrics, unfiltmetrics, BSFuji_mode):
    """
    Eventually?
    Iframe = 1
    Pframe = 2
    Bframe = 3
    #ptypes = []
    #for frame in lwiiterate(file):
    #    if "pic" in frame:
    #        ptypes.append((frame["pts"], frame["pic"]))
    #ptypes.sort()
    #ptypes = zip(*ptypes)[1]
    #ptypes = ptypes[883:]
    #print list(enumerate(ptypes))
    """
    clip = Clipinfo(cleanmetrics, clip.ranges, clip.cyclelen)
    clip_unfilt = Clipinfo(unfiltmetrics, clip.ranges, clip.cyclelen)
    winsize = clip.cyclelen*2
    winmics = deque()
    thrcombed = 8
    combed = []
    thrmocomp = 4
    scriptnnedi = []
    thrdupframe = 30
    mocomp = []
    deblockthr = 1
    deblock = []
    winmedsum = 0
    winlowsum = 0
    winsumdiff = 0
    rangenum = 0
    for i, frame in enumerate(clip.frames):
        while rangenum < len(clip.ranges) and clip.ranges[rangenum].r<=i:
            rangenum+=1
        if (rangenum >= len(clip.ranges)): break
        cyclepos = i % clip.cyclelen
        range = clip.ranges[rangenum]
        match = range.match[cyclepos]
        mic = micfrommatch(clip, i, match)
        mic_unfilt = micfrommatch(clip_unfilt, i, match)
        winmics.append(mic)
        if i>=winsize:
            micslist = list(winmics)
            micslist.sort()
            winmedsum = sum(micslist[winsize/3 : winsize/3*2])
            winlowsum = sum(micslist[0 : winsize/3])
            winsumdiff = winmedsum-winlowsum
            if (winsumdiff)/(winsize/3)>deblockthr:
                appendtorangelist(deblock, i-winsize*2/5,
                                  int(round(math.sqrt(5*winsumdiff/(winsize/3))))-2)
            winmics.popleft()
        relative_mic = mic-winlowsum/(winsize/3)
        decombed = (range.match*2).find("pc")
        if (mic>thrcombed) and (relative_mic>=thrcombed/2):
            appendtorangelist(combed, i)
            if i==0 or i>=len(clip.frames)-1: continue
            match = range.match[(cyclepos-1)%5]
            prevmic = micfrommatch(clip, i-1, match)
            match = range.match[(cyclepos+1)%5]
            nextmic = micfrommatch(clip, i+1, match)
            if (BSFuji_mode and (cyclepos!=decombed) and 
               (mic>5*min(nextmic, prevmic) or mic>1.2*(nextmic + prevmic))):
                mocompstrength = max(1, (mic*3 + (winsumdiff/(winsize/3)))/2)
                if mocompstrength>30:
                    pw = min(1, max(0, 1-(min(nextmic, prevmic)-9)/20))
                    mocompstrength = int(((mocompstrength/40.0)**pw)*40)
                #print i, prevmic, mic, nextmic
                if max(prevmic, nextmic)<4 or min(nextmic, prevmic)*3>max(nextmic, prevmic):
                    appendtorangelist(mocomp, i, mocompstrength)
                elif nextmic<prevmic:
                    appendtorangelist(scriptnnedi, i, 1)
                    appendtorangelist(mocomp, i, -mocompstrength)
                else:
                    appendtorangelist(scriptnnedi, i, 0)
                    appendtorangelist(mocomp, i, -mocompstrength)
        if (  (len(range)<5)
           or (isgoodpattern(range.match, num=True)<2)
           or (cyclepos!=decombed) or (i in [0, clip.lastframe])):
            continue
        #continue
        #low prevc/curc happens only if prev or cur frame is very similar
        prevc = clip.frames[i-1].mics[1]
        curc = clip.frames[i].mics[1]
        #lower prevp/nextp usually means that prev/cur frame is less broken
        prevp = clip.frames[i-1].mics[0]
        nextp = clip.frames[i+1].mics[0]
        prevp_unfilt = clip_unfilt.frames[i-1].mics[0]
        nextp_unfilt = clip_unfilt.frames[i+1].mics[0]
        mocompstrength = max(1, (frame.mics[0]*3 + (winsumdiff/(winsize/3)))/2)
        if (mic>thrmocomp) and (relative_mic>=thrmocomp/2):
            nnedied = True
            #define what to use on combed frames
            if (prevp*2 < min(11, nextp)) and (prevp_unfilt < 12):
                appendtorangelist(scriptnnedi, i, 0)    #nnedi3(0)
            elif (nextp*2 < min(11, prevp)) and (nextp_unfilt < 12):
                appendtorangelist(scriptnnedi, i, 1)    #nnedi3(1)
            else:
                nnedied = False
            if (min(prevc, curc)>thrdupframe or not nnedied):
                appendtorangelist(mocomp, i, mocompstrength)
            else:#positive for bidirectional mocomp, negative for unidirectional
                appendtorangelist(mocomp, i, -mocompstrength)
            #mpeg2stinx is used otherwise
        elif (prevp_unfilt==0 and nextp>=3):
            appendtorangelist(scriptnnedi, i, 0)
            appendtorangelist(mocomp, i,
                            mocompstrength * (-1 if (prevc<3) else 1))
        elif (nextp_unfilt==0 and prevp>=3):
            appendtorangelist(scriptnnedi, i, 1)
            appendtorangelist(mocomp, i,
                            mocompstrength * (-1 if (curc<3) else 1))
    return combed, deblock, mocomp, scriptnnedi

def decimate_points(clip, points):
    i = 0
    j = 0
    while (i<len(clip.ranges) and j<len(points)):
        if clip.ranges[i].r<=points[j]:
            i+=1
        else:
            dropped = points[j] / len(clip.ranges[i].match)
            if (clip.ranges[i].drop < points[j] % len(clip.ranges[i].match)):
                dropped += 1
            points[j] -= dropped
            j+=1
    while (j<len(points)):
        points[j] -= points[j] / len(clip.ranges[0].match) + 1
        j+=1
    return points

def decimate_ranges(clip, ranges, filter=True):
    points = []
    for range in ranges:
        points.append(range.l)
        points.append(range.r)
    points = decimate_points(clip, points)
    for i, range in enumerate(ranges):
        range.l = points[i*2]
        range.r = points[i*2 + 1]
    if filter:
        ranges = Clipinfo([0], ranges, None, None)
        ranges_merge(ranges)
        ranges = ranges.ranges
    return ranges

def write_tfm(clip, filename):
    with open(filename, "w") as file:
        for range in clip.ranges:
            if isgoodpattern(range.match, num=True)<2 or (len(range) < 5):
                continue
            shift = range.l % clip.cyclelen
            tfmpattern = range.match[shift:]+range.match[:shift]
            file.write(("%d,%d %s\n") % (range.l, range.r-1, tfmpattern))

def write_tdec(clip, filename):
    with open(filename, "w") as file:
        for i, range in enumerate(clip.ranges):
            if (i<len(clip.ranges)-1):
                cur = isgoodpattern(clip.ranges[i].match, num=True)
                next = isgoodpattern(clip.ranges[i+1].match, num=True)
                if (cur==1) and (next==2):
                    new = clip.ranges[i+1].l/clip.cyclelen*clip.cyclelen
                    range.r = max(new, range.l+1)
                    clip.ranges[i].r = max(new, range.l+1)
                    clip.ranges[i+1].l = max(new, range.l+1)
            if isgoodpattern(range.match, num=True)<2 or (len(range) < 5):
                range.drop = 2
                continue
            shift = range.l%clip.cyclelen
            tfmpattern = range.match[shift:]+range.match[:shift]
            range.drop = ((range.match*2).find("cp")+1)%5
            if (range.match*2).find("cp")==-1:
                range.drop = 2
            else:
                drop = (tfmpattern.find("cp")+1) % clip.cyclelen
                droppat = "+"*(drop)+"-"+"+"*(clip.cyclelen-drop-1)
                file.write(("%d,%d %s\n") % (range.l, range.r-1, droppat))

def write_scriptclip(filename, ranges, default=-1, comment=""):
    coverage = 0
    with open(filename, "w") as file:
        file.write("type int\ndefault %d\n" % default)
        file.write("#%s\n" % comment)
        for range in ranges:
            if len(range)==1:
                coverage += 1
                file.write("%d %d\n" % (range.l, range.match))
            elif len(range)>1:
                coverage += len(range)
                file.write("R %d %d %d\n" % (range.l, range.r, range.match))
    return coverage

def write_rfs(filename, ranges):
    coverage = 0
    with open(filename, "w") as file:
        i=0
        for range in ranges:
            if len(range)==1:
                coverage += 1
                file.write("%6d " % range.l)
                if (i & 15) > 14:
                    file.write("\n")
                i+=1
            elif len(range)>1:
                coverage += len(range)
                file.write("[%5d %5d] " % (range.l, range.r - 1))
                if (i & 15) > 13:
                    file.write("\n")
                i+=2
    return coverage


def processmetrics(metricsfile, prefix, sortbystrength, BSFuji_mode=False):
    for i in ["_b", "_t", "_cr"]+["_tile%d" % i for i in xrange(16)]:
        if (i+".txt") in metricsfile:
            metricsfile = metricsfile.replace(i, "")
            break
    metrics = dict()
    for suffix in ["", "_b", "_t", "_cr"]+["_tile%d" % i for i in xrange(16)]:
        if os.access((suffix+".").join(metricsfile.rsplit(".", 1)), os.R_OK):
            metrics[suffix] = readmetrics(metricsfile, suffix)
    mergetilemetrics(metrics)
    finfo = metrics[""]
    clip = Clipinfo(frames=finfo, ranges=None, cyclelen=5, chunklen=120)
    makeranges(clip)
    processranges_good(clip)
    finfo_top = metrics["_t"]
    finfo_bottom = metrics["_b"]
    finfo_chroma = metrics["_cr"]
    mixtop, mixbottom = merge_t_b_chroma(clip, finfo_top, finfo_bottom, finfo_chroma)
    for i in metrics:
        if i!="":
            removeuselessmetrics(clip, metrics[i])
    unfilt = metrics[""]
    mergetilemetrics(metrics, bord=True)
    #some unfinished shit you probably don't need
    #crossfades60i = find60icrossfades(clip)
    #print "possible 60i crossfades: "+str(crossfades60i)
    patterninfo = (['Patterns in "[start, end) len pattern" format'] +
        [str("[%d, %d) %d %s") % (range.l, range.r, len(range), range.match)
         for range in clip.ranges])
    write_tfm(clip, prefix+"tfmovr.txt")
    write_tdec(clip, prefix+"tdcovr.txt")
    mixtopinfo = (['IVTC_TXT30MC/IVTC_TXT60MC on top part of frame(not decimated):'] + 
        [str("[%d, %d)") % (range.l, range.r) for range in mixtop])
    mixbotinfo = (['IVTC_TXT30MC/IVTC_TXT60MC on bottom part of frame(not decimated):'] + 
        [str("[%d, %d)") % (range.l, range.r) for range in mixbottom])
    mixtop = decimate_ranges(clip, mixtop)
    mixbottom = decimate_ranges(clip, mixbottom)
    mixcomment = "value<%d for 60i, value>=%d for 30p" % (clip.cyclelen, clip.cyclelen)
    mixtoplen = write_scriptclip(prefix+"mixtop.txt", mixtop, comment=mixcomment)*5/4
    mixbotlen = write_scriptclip(prefix+"mixbot.txt", mixbottom, comment=mixcomment)*5/4
    stinx, deblock, mocomp, nnedi = PP(clip, metrics[""], unfilt, BSFuji_mode)
    nnedi = decimate_ranges(clip, nnedi)
    stinx = decimate_ranges(clip, stinx)
    vardeblock = copy.deepcopy(deblock)
    for i in deblock:
        i.match = None
    deblock = decimate_ranges(clip, deblock)
    vardeblock = decimate_ranges(clip, vardeblock)
    mocomp = decimate_ranges(clip, mocomp)
    if sortbystrength:
        vardeblock.sort(key=lambda x:x.match)
        mocomp.sort(key=lambda x:x.match)
    stinxcoverage = write_rfs(prefix+"m2s2maps.txt", stinx)
    deblockcoverage = write_rfs(prefix+"deblock.txt", deblock)
    write_scriptclip(prefix+"vardeblock.txt", vardeblock)
    write_rfs(prefix+"deblock.txt", deblock)
    mocompcoverage = write_scriptclip(prefix+"mc_presets.txt", mocomp, default=0)
    mocomp.sort()
    write_rfs(prefix+"mcm.txt", mocomp)
    write_scriptclip(prefix+"nnedi.txt", nnedi)
    ppinfo =["PP: %d fields nnedi'd, %d frames stinx"
             % (len(nnedi), stinxcoverage),
           "       %d frames deblocked, %d frames mocomped"
             % (deblockcoverage, mocompcoverage)]
    msg = "\n".join(patterninfo+mixtopinfo+mixbotinfo+ppinfo)
    with open(prefix+"info.txt", "w") as file:
        file.write(msg)
    return "(Saved to %s)\n" % (prefix+"info.txt") + msg

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print "Script requires one metric filename"
    else:
        metricsfile = sys.argv[1]
        prefix = sys.argv[2] if (len(sys.argv) > 2) else ""
        sortbystrength = True
        print processmetrics(metricsfile, prefix, sortbystrength)
