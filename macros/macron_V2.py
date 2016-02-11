from macron_parse import lwiiterate
import bisect
import subprocess
import re
import os


def mkvframecount(filename):
    frame_re = re.compile("Track ID .{0,5} video.*tag_number_of_frames:([0-9]*?) .*")
    cmd = ["mkvmerge", "-I", filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in proc.stdout:
        t = frame_re.match(line)
        if t:
            return int(t.group(1))
    return -1

class Mkvsplitpart:
    def __init__(self, range, split, redo):
        self.range = range
        self.split = split
        self.redo = redo
    
    def __repr__(self):
        return str((self.range, self.split, self.redo))
    
    def cmdrange(self):
        return "%d-%d" % (self.split)

def parseranges(strranges):
    ranges1 = strranges.split("[")
    ranges = [(int(frame), int(frame)+1) for frame in ranges1[0].split()]
    for range in ranges1[1:]:
        rng = range.split("]")[0].split()
        ranges.append((int(rng[0]), int(rng[1])))
        ranges += [(int(frame), int(frame)+1) for frame in range.split("]")[1].split()]
    return ranges

options = avsp.GetTextEntry(
            title="Macron_V2",
            message=[["V1 mkv file"],
                     ["Ranges you want to redo, in RFS format"],
                     ["Encode command, without --frames, --seek and -o"]],
            default=[[""],
                     [""],
                     ["avs4x26xmod script.avs"]],
            types=  [["file_open"],
                     ["text"],
                     ["text"]],
            width=640)
            
if len(options)<1:
    return
filepath = options[0]
ranges = options[1]
ranges = parseranges(ranges)
ranges.sort()
enccommand = options[2]
index = filepath+".lwi"
if not os.access(index, os.F_OK):
    avsp.NewTab(copyselected=False)
    avsp.InsertText('lwlibavvideosource("%s")' % filepath)
    avsp.UpdateVideo()
    avsp.CloseTab()

vframes = []
for frame in lwiiterate(index):
    if "key" in frame:
        vframes.append(frame)
vframes.sort(key=(lambda x: x["pts"]))

keyframes = [0]
for i, frame in enumerate(vframes):
    if frame["key"]==1:
        keyframes.append(i)

new_l = 0
new_r = 0
snapranges = []
for range in ranges:
    l = keyframes[bisect.bisect_right(keyframes, range[0])-1]
    r = keyframes[bisect.bisect_left(keyframes, range[1])]
    if l>new_r:
        if new_r>new_l:
            snapranges.append((new_l, new_r))
        new_l, new_r = l, r
    else:
        new_r = r
if new_r>new_l:
            snapranges.append((new_l, new_r))

framecount = mkvframecount(filepath)
if framecount!=len(vframes):
    print "Warning: mkvmerge reports %d frames but .lwi has %d frames" % (framecount, len(vframes))

keyframes.append(framecount)

parts = []

for range in snapranges:
    lkey = bisect.bisect(keyframes, range[0])-1
    #l = keyframes[lkey]
    l = (keyframes[lkey-1]+keyframes[lkey]+1)/2+1
    rkey = bisect.bisect(keyframes, range[1])-1
    #r = keyframes[rkey]
    r = (keyframes[rkey-1]+keyframes[rkey]+1)/2
    curpart = Mkvsplitpart(range, (l, r), True)
    prevrangel = parts[-1].range[1] if len(parts)>0 else 0
    prevsplitl = (parts[-1].split[1]+1) if len(parts)>0 else 1
    prevpart = Mkvsplitpart((prevrangel, range[0]), (prevsplitl, l-1), False)
    if prevpart.range[1]>prevpart.range[0]:
        parts.append(prevpart)
    parts.append(curpart)

if (parts[-1].range[1] < framecount):
    parts.append(Mkvsplitpart((parts[-1].range[1], framecount),
                              (parts[-1].split[1]+1, framecount), False))

splitcmd = "frames:"+",".join([str(part.split[1]) for part in parts])

tempname = filepath.rsplit(".", 1)[0]+"_part_%03d.mkv"
cmd = ["mkvmerge", filepath, "--split", splitcmd, "-o", tempname]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
proc.wait()

frame = 0
for i, part in enumerate(parts):
    framecount_part = mkvframecount(tempname % (i+1))
    if part.range != (frame, frame+framecount_part):
        print ("Warning, resulting split (%d, %d) isn't same as target range (%d, %d)" %
                (frame, frame+framecount_part, part.range[0], part.range[1]))
        part.range = (frame, frame+framecount_part)
    frame += framecount_part

for range in ranges:
    if any((part.range[0]<=range[0]<=range[1]<=part.range[1] for part in parts)):
        continue
    else:
        print "Range (%d, %d) can't be redone with such splits, exiting" % range
        return

batname = filepath.rsplit(".", 1)[0]+"_part_%03dv2.bat"
muxbatname = filepath.rsplit(".", 1)[0]+"_mux.bat"
appendlist = []
allbatname = filepath.rsplit(".", 1)[0]+"_all.bat"
allbat = "call "
reenc_ranges = []

for i, part in enumerate(parts):
    if part.redo:
        #os.remove(tempname % (i+1))
        with open(batname % (i+1), "w") as bat:
            h264name = tempname.rsplit(".", 1)[0] % (i+1) + "v2.h264"
            mkvname = tempname.rsplit(".", 1)[0] % (i+1) + "v2.mkv"
            bat.write(enccommand+" --seek %d --frames %d -o %s" % 
                     (part.range[0], part.range[1]-part.range[0], h264name))
            bat.write("\nmkvmerge %s -o %s" % (h264name, mkvname))
            appendlist.append(mkvname)
            reenc_ranges.append(part.range)
        allbat += batname % (i+1) + "\ncall "
    else:
        appendlist.append(tempname % (i+1))

dontcopy = " -A -S -B -T -M --no-chapters --no-global-tags "
with open(muxbatname, "w") as bat:
    bat.write("mkvmerge "+dontcopy + (dontcopy+" +").join(appendlist)
              +" -D "+filepath+" -o "+ filepath.rsplit(".", 1)[0]+"v2.mkv")

with open(allbatname, "w") as bat:
    bat.write(allbat+muxbatname)

avsp.MsgBox("Ranges %s will be redone. \nUse %s to reencode and mux, or run %s and %s manually"
         % (str(reenc_ranges), allbatname, batname, muxbatname))
