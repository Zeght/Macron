import re

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
    framelen =  Fraction(ref2["pts"]-ref["pts"], ref2["localpoc"] - ref["localpoc"])
    firstpts = ref["pts"] - framelen*ref["localpoc"]
    postfirstkeypts = firstpts + framelen*vid[postfirstkey]["localpoc"]
    delayFF = (aud[0]["pts"] - firstpts) * ref["timebase"]
    delayDG = (aud[0]["pts"] - postfirstkeypts) * ref["timebase"]
    return (int(round(delayFF*1000)), int(round(delayDG*1000)), vid[postfirstkey]["localpoc"])

def mkvframecount(filename):
    frame_re = re.compile("Track ID .{0,5} video.*tag_number_of_frames:([0-9]*?) .*")
    cmd = ["mkvmerge", "-I", filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in proc.stdout:
        t = frame_re.match(line)
        if t:
            return int(t.group(1))
    return -1

aq = ["aq", "aq2", "aq3"]
aqfactors = [aqi+"-factor" for aqi in aq]
aqdb = ["deblock"] + aqfactors + aq
customfix = {"keyint-min" : "min-keyint",
             "decimate" : "dct-decimate",
             "mixed_ref" : "mixed-refs"}
disableflags = ["mixed-refs", "chroma-me", "8x8dct",
                "fast-pskip", "dct-decimate"]
enableflags = ["bluray-compat", "constrained-intra",
               "intra-refresh", "open-gop", "sliced-threads"]
removeopts = ["analyse", "aq2-mode", "interlaced", "rc"]

def possplit(s, spl):
    spl.append(len(s)+1)
    res = [s[:spl[0]]]
    for i in xrange(1,len(spl)):
        if (spl[i] - spl[i-1] > 0):
            res.append(s[spl[i-1]+1 : spl[i]])
    return res

def fixaqdb(opt, params):    #convert logged aq or deblock opts to cli opts
    if (opt == "deblock"):
        params = params[2:]
        return [(opt, params)]
    elif (opt in aqfactors):
        col = []
        d = 0
        for i in xrange(0, len(params)):
            if (params[i] == "["):
                d += 1
            elif (params[i] =="]"):
                d -= 1
            elif (params[i] == ":") and (d == 0):
                col.append(i)
        aqf = opt.split("-")
        opts = [ftype.join(aqf) for ftype in ["-i", "-p", "-b"]]
        params = [p.strip("[]") for p in possplit(params, col)]
        return zip(opts, params)
    elif (opt in aq):
        params = params.split(':', 1)
        if (len(params) > 1):
            opts = [opt + "-mode", opt + "-strength"]
            params[1] = params[1].translate(None, "[]")
        else:
            opts = [opt + "-mode"]
        opts = zip(opts, params)
        return opts
    return []

def getcqpoffsetsub(opts, sub=0):
    if ("psy-rd" in opts):
        values = opts["psy-rd"].split(":")
        for i in values:
            psy = float(i)
            if psy > 0:
                sub += 1
                if psy > 0.25:
                    sub+=1
    return sub

def getopts(field, i444=False):
    deunderscore = {"me_range", "mv_range", "qp_min", "qp_max",
                    "ip_ratio", "pb_ratio"}
    if field == None:
        return None
    if not(type(field) is str):
        field = field.text
    splitchar = "/" if ("/" in field) else " "
    field = field.translate(None, chr(9))
    opts = dict()
    for opt in field.split(splitchar):
    #for opt in field.split("/"):
        opt, param = opt.strip().split("=", 1)
        if (opt in deunderscore):
            opt = opt.replace("_", "")
        if (opt in aqdb):
            for optparam in fixaqdb(opt, param):
                opts[optparam[0]] = optparam[1]
        else:
            opt = opt.replace("_", "-")
            opt = customfix.get(opt, opt)
            if opt=="direct":
                param = ["none", "spatial", "temporal", "auto"][int(param)]
            if opt=="cqm":
                param = ["flat", "jvt"][int(param)]
            if (opt in disableflags):
                if int(param)==0:
                    opts["no-"+opt] = ""
            elif (opt in enableflags):
                if int(param)==1:
                    opts[opt] = ""
            elif opt=="deadzone":
                opts["deadzone-inter"], opts["deadzone-intra"] = param.split(",")
            else:
                opts[opt] = param
    
    for i in removeopts:
        opts.pop(i, None)
    if "chroma-qp-offset" in opts:
        add = getcqpoffsetsub(opts, sub=-6 if i444 else 0)
        opts["chroma-qp-offset"] = str(int(opts["chroma-qp-offset"])+add)
    return opts

def extractx264opts(filename):
    link = "http://www.videolan.org/x264.html"
    params = None
    with open(filename, "rb") as file:
        t = file.read(16)
        c = 0
        while (len(t)>0) and (c<10**6):
            if t in link:
                params=t
                break
            t = file.read(16)
            c+=1
        if not params:
            return None
        while chr(0) not in t:
            t = file.read(16)
            params+=t
    params = params.split(chr(0))[0]
    return params.split("options: ")[-1]
