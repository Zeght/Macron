import re
#from fractions import Fraction

max_frame = 10000000

def lwiiterate(filename):
    ints = ["Index", "Type", "Codec", "POS", "PTS", "DTS", "EDI",
            "Rate", "BPS", "Length", "Key", "Pic", "POC", "Repeat",
            "Field", "Width", "Height", "ColorSpace"]
    vals = None
    q=0
    with open(filename, "r") as file:
        for line in file:
            if "</LibavReaderIndex>" in line:
                if vals!=None:
                    yield vals
                break
            if line[:5]=="Index":
                if vals!=None:
                    yield vals
                vals = dict()
            if vals!=None:
                for i in line.split(","):
                    i = i.split("=")
                    if (i[0] in ints):
                        val = int(i[1])
                    elif (i[0]=="TimeBase"):
                        val = float(i[1].split("/")[0])/float(i[1].split("/")[1])
                    else:
                        val = i[1]
                    vals[i[0].lower()] = val

def getAVshifts(filename):
    #from fractions import Fraction
    vid = list()
    aud = list()
    for i in lwiiterate(filename):
        if "channels" in i:
            aud.append(i)
        elif i.get("field", 2)!=2:
            vid.append(i)
        if min(len(vid), len(aud))>1000:
            break
    firstkey = 0
    while (vid[firstkey]["key"] != 1):
        firstkey += 1
    postfirstkey = firstkey
    for i, frame in enumerate(vid[firstkey:]):
        if frame["pts"]<=vid[postfirstkey]["pts"]:
            postfirstkey = firstkey+i
    
    if len(vid)==0 or len(aud)==0:
        return (0, 0, 0)
    elif len(vid)==1:
        return (vid[0]["pts"]-aud[0]["pts"], vid[0]["pts"]-aud[0]["pts"], 0)
    
    ptsorder = range(len(vid))
    ptsorder.sort(key=lambda x:vid[x]["pts"])
    for i, fnum in enumerate(ptsorder):
        vid[fnum]["localpoc"] = i
    
    ref = vid[-1 - len(vid)*3/5]
    ref2 = vid[len(vid)*3/5]
    framelen =  float(ref2["pts"]-ref["pts"]) / (ref2["localpoc"] - ref["localpoc"])
    firstpts = ref["pts"] - framelen*ref["localpoc"]
    postfirstkeypts = firstpts + framelen*vid[postfirstkey]["localpoc"]
    delayFF = (aud[0]["pts"] - firstpts) * ref["timebase"]
    delayDG = (aud[0]["pts"] - postfirstkeypts) * ref["timebase"]
    return {"delayFF":int(round(delayFF*1000)), 
            "delayDG":int(round(delayDG*1000)),
            "DG_FF_diff":vid[postfirstkey]["localpoc"]}

def mkvframecount(filename):
    frame_re = re.compile("Track ID .{0,5} video.*tag_number_of_frames:([0-9]*?) .*")
    cmd = ["mkvmerge", "-I", filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in proc.stdout:
        t = frame_re.match(line)
        if t:
            return int(t.group(1))
    return -1

def split_avsi_lines(s):
    lines = s.splitlines()
    concat_lines = [""]
    concat_next = False
    for line in lines:
        if concat_next:
            concat_lines[-1] += line
        else:
            ls = line.lstrip()
            if (len(ls)>0) and ls[0]=="\\":
                concat_lines[-1] += line
            else:
                concat_lines.append(line)
        if len(line)>0 and line[-1]=="\\":
            concat_next = True
    return concat_lines

def parse_ranges(ranges_str):
    ranges1 = ranges_str.split("[")
    # a b c d e [f g]h[i j]
    #range[0]^
    ranges = [(int(frame), int(frame)+1) for frame in ranges1[0].split()]
    for range in ranges1[1:]:
        range, lone_frames = range.split("]")
        ranges.append((int(range.split()[0]), int(range.split()[1])))
        ranges += [(int(frame), int(frame)+1) for frame in lone_frames.split()]
    return ranges

def parse_spliced_trims(trims_str):
    trims_str = trims_str.lower().replace("trim", "").replace("++", "+")
    ranges = []
    for trim in trims_str.split("+"):
        trim = trim.split("(")[1].split(")")[0].split(",")
        a = int(trim[0])
        b = int(trim[1])
        if (b<0):
            b = a - b
        elif (b>0):
            b = b + 1
        else:
            b = max_frame
        ranges.append((a, b))
    return ranges

def parse_fps(s):
    if "/" in s:
        n, d = s.split("/")
        return float(n)/float(d)
    else:
        return float(s)
