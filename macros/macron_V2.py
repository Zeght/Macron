import macron_parse
macron_parse.avsp = avsp
import bisect
import subprocess
import re
import os

def mkvframecount(filename):
    framenum_tag_re = re.compile("Track ID .{0,5} video.*tag_number_of_frames:([0-9]*?) .*")
    uid_re = re.compile("Track ID .{0,5} video.*uid:([0-9]*).*")
    cmd = ["mkvmerge", "-I", filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    videouids = []
    for line in proc.stdout:
        framenum = framenum_tag_re.match(line)
        if framenum:
            return int(framenum.group(1))
        uid = uid_re.match(line)
        if uid:
            videouids.append(int(uid.group(1)))
    cmd = ["mkvextract", "tags", filename]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    xml = proc.stdout.read()
    proc.communicate()
    tracks = xml.split("<TrackUID>")
    for track in tracks:
        if str(videouids[0]) in track:
            track = track.split("<Name>NUMBER_OF_FRAMES</Name>")[-1]
            if "<String>" not in track: continue
            frames = track.split("<String>")[1]
            if "</String>" not in track: continue
            frames = frames.split("</String>")[0]
            return int(frames)
    
    #Avs doesn't have ElementTree library
    """tree = ET.fromstring(t)
    for tag in tree:
        targets = tag.find("Targets")
        if targets is None: continue
        uid = targets.find("TrackUID")
        if uid is None: continue
        uid = int(uid.text)
        if uid not in videouids: continue
        for simpletag in tag:
            name = simpletag.find("Name")
            if name is not None and name.text=="NUMBER_OF_FRAMES":
                string = simpletag.find("String")
                if string is not None:
                    return int(string.text)"""
    return -1

class Mkvsplitpart:
    def __init__(self, range, split, toprocess):
        self.range = range
        self.split = split
        self.toprocess = toprocess
    
    def __repr__(self):
        return str((self.range, self.split, self.toprocess))
    
    def cmdrange(self):
        return "%d-%d" % (self.split)

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
ranges = macron_parse.parse_ranges(ranges)
ranges.sort()
if len(ranges)==0:
    avsp.MsgBox("No ranges, exiting")
    return
enccommand = options[2]
            
keyframes = macron_parse.get_keyframes(filepath, include_end=True)

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
if framecount!=keyframes[-1]:
    print "Warning: mkvmerge reports %d frames but .lwi has %d frames" % (framecount, keyframes[-1])

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
proc.communicate()

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
    if part.toprocess:
        #os.remove(tempname % (i+1))
        with open(batname % (i+1), "w") as bat:
            h264name = tempname.rsplit(".", 1)[0] % (i+1) + "v2.h264"
            mkvname = tempname.rsplit(".", 1)[0] % (i+1) + "v2.mkv"
            bat.write(enccommand+' --seek %d --frames %d -o "%s"' % 
                     (part.range[0], part.range[1]-part.range[0], h264name))
            bat.write('\nmkvmerge "%s" -o "%s"' % (h264name, mkvname))
            appendlist.append('"%s"' % mkvname)
            reenc_ranges.append(part.range)
        allbat += 'call "%s"\n' % (batname % (i+1))
    else:
        appendlist.append('"%s"' % (tempname % (i+1)))

filepathv2 = filepath.rsplit(".", 1)[0]+"v2.mkv"
dontcopy = " -A -S -B -T -M --no-chapters --no-global-tags "
with open(muxbatname, "w") as bat:
    bat.write("mkvmerge "+dontcopy + (dontcopy+" +").join(appendlist)
              +' -D "%s" -o "%s"' % (filepath, filepathv2))

with open(allbatname, "w") as bat:
    allbat += 'call "%s"\n' % muxbatname
    bat.write(allbat)

avsp.MsgBox("Ranges %s will be redone. \nUse %s to reencode and mux, or run %s and %s manually"
         % (str(reenc_ranges), allbatname, batname, muxbatname))
