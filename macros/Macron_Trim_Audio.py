import macron_parse
import subprocess
import re
import os

def format_duration(ms):
    s = ms/1000
    ms = ms % 1000
    m = s/60
    s = s%60
    h = m/60
    m = m%60
    return "%d:%d:%d.%d" % (h, m, s, ms)

def getstrings(line):
    strings = []
    bigstrings = line.split("\"\"\"")
    for i, bigstring in enumerate(bigstrings):
        if i % 2 == 0:
            for ii, string in enumerate(bigstring.split("\"")):
                if ii % 2 == 1:
                    strings.append(string)
        else:
            strings.append(string)
    return strings

def find_source_plugin(s):
    for line in s.splitlines():
        line = line.lower()
        if "mpeg2source" in line or "dgdecode" in line:
            return "DG"
        elif "lwlibavvideosource" in line or "avsource(" in line or "ffvideo" in line:
            return "FF"
    return "FF"
                
def find_videofile(s):
    extensions = ["ts",
                  "m2ts",
                  "mkv", 
                  "vob",
                  "d2v"]
    for line in s.splitlines():
        strings = getstrings(line)
        for s in strings:
            if ("." in s and s.rsplit(".", 1)[-1].lower() in extensions):
                return s
    return ""

def find_trims(s):
    lines = macron_parse.split_avsi_lines(s)
    for line in lines:
        line = line.lower()
        if "trim" in line:
            line = line[line.find("trim"):]
            mid , trim , tail = line.rpartition("trim")
            tail, br, _ = tail.partition(")")
            return mid+trim+tail+br
        bigstrings = line.split("\"\"\"")
        strings = getstrings(line)
        if len(strings) == 0:
            strings.append(line.lstrip("#"))
        for string in strings:
            try:
                string = string.encode('ascii', 'replace')
            except:
                string = ""
            if "[" in string and string.translate(None, "1234567890[] ") == "":
                return string
    return ""

script = avsp.GetText()
defaultfps = ["24000/1001",
              "30000/1001"]
defaultsource = ["DGDecode/MPEG2Source",
                 "FFMS/L-Smash"]
if ("DG" in find_source_plugin(script)):
    defaultsource.append("DGDecode/MPEG2Source")
else:
    defaultsource.append("FFMS/L-Smash")

filepath = find_videofile(script)
trims = find_trims(avsp.GetSelectedText())
if trims == "":
    trims = find_trims(script)
options = avsp.GetTextEntry(
            title="Macron_Trim_Audio",
            message=[["Video source filter"],
                     ["File vith video/audio"],
                     ["Spliced trims or RFS string"],
                     ["Framerate"]],
            default=[[defaultsource],
                     [filepath],
                     [trims],
                     [defaultfps]],
            types=  [["list_read_only"],
                     ["file_open"],
                     ["text"],
                     ["list_writable"]],
            width=640)

if len(options)<1:
    return
source = options[0][:2]
filepath = options[1]
ranges = options[2].lower()
if "trim" in ranges:
    ranges = macron_parse.parse_spliced_trims(ranges)
else:
    ranges = macron_parse.parse_ranges(ranges)
fps = macron_parse.parse_fps(options[3])
if fps is None:
    avsp.MsgBox("Invalid FPS value: %s" % (options[3]))
    return
ranges.sort()
if source=="FF":
    index = filepath + ".lwi"
    if not os.access(index, os.F_OK):
        avsp.NewTab(copyselected=False)
        avsp.InsertText('lwlibavvideosource("%s")' % filepath)
        avsp.UpdateVideo()
        avsp.CloseTab()

    delays = macron_parse.getAVshifts(index)
    delay = delays["delayFF"]-delays["delayDG"]
else:
    delay = 0
name_template = filepath.rsplit(".", 1)[0]
extracted = name_template + ".aac"
extracted_mka = name_template + ".mka"
final_mka = name_template + "_trimmed.mka"

extract_cmd = ["eac3to", filepath, "2:", extracted]
extract_proc = subprocess.Popen(extract_cmd)
extract_proc.communicate()
mux_cmd = ["mkvmerge", extracted, "-o", extracted_mka]
mux_proc = subprocess.Popen(mux_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
mux_proc.communicate()
parts = []
for cur_range in ranges:
    timecode1 = format_duration(int(cur_range[0]/fps*1000-delay))
    timecode2 = format_duration(int(cur_range[1]/fps*1000-delay))
    if cur_range[1]==macron_parse.max_frame:
        timecode2=""
    parts.append("-".join((timecode1, timecode2)))

splitcmd = "parts:"+",+".join(parts)
trim_cmd = ["mkvmerge", extracted_mka, "--split", splitcmd, "-o", final_mka]
trim_proc = subprocess.Popen(trim_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
trim_proc.communicate()

avsp.MsgBox("Trimmed. Delay=%d, Trims: %s"
         % (delay, parts))
