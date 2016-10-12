import sys
import os
import subprocess
import re
from time import sleep
from threading import Thread
import contextlib
import Queue

scripthead = """
    Function DumpTFM(clip src, string filename)
    {
        return src.tfm(slow=0, pp=0, micout=1, output=filename).crop(0,0,2,2)
    }
    setmemorymax(64)
    %(src)s
    RequestLinear()
    h = Height()
    w = Width()
    crh = h/18*4
    last"""
scriptquick ="""
    crop(w/12*4, 0, w/12*4, 0)
    t = crop(8,       8, -8, crh-8).DumpTFM("%(out)s_t.txt")
    b = crop(8, h-crh-8, -8,    -8).DumpTFM("%(out)s_b.txt")
    c = crop(8,     crh,  8,  -crh)
    chroma = stackhorizontal(c.UToY(),c.VToY()).DumpTFM("%(out)s_cr.txt")
    c = c.DumpTFM("%(out)s_tile0.txt")
    StackVertical(t,b,c,chroma)"""
scriptregular="""
    t = crop(8,       8, -8, crh-8).DumpTFM("%(out)s_t.txt")
    b = crop(8, h-crh-8, -8,    -8).DumpTFM("%(out)s_b.txt")
    c = crop(8,     crh, -8,  -crh)
    chroma = stackhorizontal(c.UToY(),c.VToY()).DumpTFM("%(out)s_cr.txt")
    
    w    = c.Width()
    crh  = c.Height()/4*2
    crw  = w*2/32*2
    crw2 = w*5/32*2
    
    ll = c.crop(    0,   0, crw,    0).DumpTFM("%(out)s_tile1.txt")
    l  = c.crop(  crw,   0, crw2,    0)
    lt = l.crop(    0,   0,    0, -crh).DumpTFM("%(out)s_tile2.txt")
    lb = l.crop(    0, crh,    0,    0).DumpTFM("%(out)s_tile3.txt")
    
    r  = c.crop(w-crw-crw2,    0, -crw,    0)
    rt = r.crop(         0,    0,    0, -crh).DumpTFM("%(out)s_tile4.txt")
    rb = r.crop(         0,  crh,    0,    0).DumpTFM("%(out)s_tile5.txt")
    rr = c.crop(w-crw     ,    0,    0,    0).DumpTFM("%(out)s_tile6.txt")
    
    c  = c.crop(crw+crw2, 0, -crw-crw2, 0).DumpTFM("%(out)s_tile0.txt")
    stackvertical(t, b, ll, lt, lb, rt, rb, rr, c, chroma)
    """

def cmdfromrange(avspath, num, seek, frames, a2y=False):
    return (["avs2yuv", "-raw", "-v",
             "-seek", "%d" % seek,
             "-frames", "%d" % frames,
             avspath%num, "-"])




newlines = ['\n', '\r\n', '\r']

def runthread(avspath, num, seek, frames, progresshack, qu, killevents):
    def unbuffered(proc, stream='stdout'):#tfw still buffered
        stream = getattr(proc, stream)
        with contextlib.closing(stream):
            while True:
                out = []
                last = stream.read(1)
                if last == '' and proc.poll() is not None:
                    break
                while last not in newlines:
                    if last == '' and proc.poll() is not None:
                        break
                    out.append(last)
                    last = stream.read(1)
                out = ''.join(out)
                yield out
    
    cmd = cmdfromrange(avspath, num, seek, frames)
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=open(os.devnull, 'w'))
    progresshack-=1
    for line in unbuffered(process, "stderr"):
        if killevents and killevents[0].is_set():
            process.kill()
            break
        if not 0<len(line)<10: continue
        framenum = int(line)
        if framenum&progresshack==0:
            qu.put((num, framenum))
    qu.put((num, False))

def getmetrics(avspath, scriptsrc, outfile, outext, threads, seek, frames, quick, ignorecorner=True, progresshack=0, keep=False, avspmacro=False, killevents=None):
    threads = min(threads, frames/100 + 1)
    outfile = os.path.abspath(outfile)
    tempfile = outfile+"_%d"
    threadlist = []
    script = (scripthead+(scriptquick if quick else scriptregular)
              +"interleave(last, last)\n    "*progresshack)
    if ignorecorner:
        script = script.replace("t = crop(8,       8, -8, crh-8)", "t = crop(8,       8, -256,  crh-8)")
    for i in xrange(0, threads):
        with open(avspath%i, "w") as avsfile:
            avsfile.write(script % {"src" : scriptsrc, "out":tempfile%i})
    progresshack = 2**progresshack
    sleep(0.1)
    qu = Queue.Queue()
    for i in xrange(0, threads):
        thrframes = (frames/threads) if (i+1<threads) else (frames-(frames/threads)*(threads-1))
        threadlist.append(Thread(target=runthread, 
                                args=(avspath, i, (seek+(frames/threads)*i)*progresshack, thrframes*progresshack, progresshack,
                                      qu, killevents)))
        threadlist[-1].start()
    progress = [0]*threads
    target = [frames/threads]*(threads-1) + [frames-(frames/threads)*(threads-1)]
    done = 0
    global metricsfile
    metricsfile = outfile+outext
    yield sum(target)
    while done<threads:
        try:
            q = qu.get(timeout=1)
        except (Queue.Empty):
            yield sum(progress)
            continue
        if type(q[1]) is int:
            progress[q[0]] += 1
            if sum(progress)&127==0 or progresshack>4:
                yield sum(progress)
        else:
            done += 1
    if sum(progress)&15!=0 and progresshack<=16:
        yield sum(progress)
    if (not killevents or not killevents[0].is_set()) and (progress!=target):
        print ("Warning: not all frames were processed\nProcessed:%s\nTarget:%s"
                                                % (str(progress), str(target)))
    for thread in threadlist:
        thread.join()
    suffixes = []
    for suffix in ["", "_b", "_t", "_cr"]+["_tile%d" % i for i in xrange(16)]:
        if os.access(tempfile%0+suffix+".txt", os.R_OK):
            suffixes.append(suffix)
    for suffix in suffixes:
        with open(outfile+suffix+outext, "w") as bigfile:
            for i in xrange(0, threads):
                with open(tempfile%i+suffix+".txt", "r") as tmpfile:
                    bigfile.write(tmpfile.read()+"\n")
                if not keep:
                    os.remove(tempfile%i+suffix+".txt")
    if not keep:
        for i in xrange(0, threads):
            os.remove(avspath%i)
    yield -1

def parse_args(args):
    import argparse
    import multiprocessing
    parser = argparse.ArgumentParser(description="TFM metrics collector")
    
    parser.add_argument(nargs=1, type=str, dest="input", metavar="<filename>",
                        help="path  to mediafile(will be loaded with lwlibavvideosource)"
                              +"or path to .avs script."
                              +"Note that file should be loaded with same source filter as your main script"
                              +"to ensure same frame numbering")
    parser.add_argument("-t", "--threads", default=multiprocessing.cpu_count(),
                        type=int, metavar="T", dest="threads",
                        help="Number of avs2yuv processes")
    parser.add_argument("-s", "--seek", default=0,
                        type=int, metavar="S", dest="seek",
                        help="Seek to frame instead of processing whole clip")
    parser.add_argument("-f", "--frames", default=0,
                        type=int, metavar="F", dest="frames",
                        help="0 - process all frames, otherwise process only first F frames")
    parser.add_argument("-k", "--keep", action='store_true', dest="keep",
                        help="keep temporary files")
    parser.add_argument("-q", "--quick", action='store_true', dest="quick",
                        help="Enable quick mode - less reliable metrics at double speed.")
    parser.add_argument("-p", "--progresshack", default=0,
                        type=int, metavar="P", dest="progresshack",
                        help="Nasty hack to increase progress update rate. Makes rate 2^P times higher.")
    parser.add_argument("-o", "--output", default="", dest="output", metavar="<filename>",
                        help="Name for outputted metrics file, default - [sourcepath]_metrics")
    return parser.parse_args(args)            

def cli():
    args = parse_args(sys.argv[1:])
    srcpath = os.path.abspath(args.input[0])
    scriptsrc = (open(srcpath).read() if srcpath[-4:]==".avs"
                 else 'lwlibavvideosource("%s")' % srcpath)
    outfile, outext  = (os.path.splitext(args.output) if (args.output!="")
             else (os.path.splitext(srcpath)[0]+"_metrics", ".txt"))
    avspath = os.path.splitext(srcpath)[0]+"_metrics_%d.avs"
    threads = args.threads
    seek = args.seek
    frames = args.frames
    keep = args.keep
    quick = args.quick
    progresshack = args.progresshack
    
    with open(avspath%0, "w") as avsfile:
        avsfile.write(scripthead % {"src" : scriptsrc, "out":outfile})
    cmd = ["avs2yuv", avspath%0, "-frames", "1", "-"]
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    out, err = process.communicate()
    process.wait()
    os.remove(avspath%0)
    framecount = re.search("([0-9]*) frames", err)
    if not framecount:
        print "error, couldn't get framecount from source\n%s" % err
        exit(0)
    framecount = int(framecount.group(1))
    frames = (framecount-seek) if (frames==0) else frames
    progress = getmetrics(avspath, scriptsrc, outfile, outext, threads, seek, frames,
                                          quick, progresshack=progresshack, keep=keep)
    target = progress.next()
    print "Target:%d frames" % target
    last = pr = 0
    while pr>=0:
        if (last!=pr>0):
            print "%d/%d" % (pr, target)
        last = pr
        pr = progress.next()

if __name__ == "__main__":
    cli()
