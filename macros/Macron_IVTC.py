import os
import macron_ivtc_getmetrics
import macron_ivtc_processmetrics
import textwrap
import threading

scriptsrc = avsp.GetText()
srcpath = avsp.GetScriptFilename()
outfile = os.path.splitext(srcpath)[0]+"_metrics.txt"
prefix = os.path.splitext(srcpath)[0]+"_"
framecount = avsp.GetVideoFramecount()
options = avsp.GetTextEntry(
            title="Collect TFM mertics",
            message=[["Merics filename"], 
                     ["Use existing metrics istead of generating", "Threads", "Ignore top right corner"],
                     ["Metrics processing"],
                     ["Prefix for outputted files"],
                     ["Sort ScriptClip output by value instead of frame number"]],
            default=[[outfile],
                     [False, (4, 1), False],
                     [None],
                     [prefix],
                     [True]],
            types=  [["file_save"],
                     ["check", "spin", "check"],
                     ["sep"],
                     ["text"],
                     ["check"]],
            width=440)
if not options: return
outfile, outext = os.path.splitext(options[0])
if not options[1]:
    seek, frames = 0, framecount
    threads = options[2]
    ignorecorner = options[3]
    avspath = os.path.splitext(srcpath)[0]+"_metrics_%d.avs"
    frames = min(frames, framecount - seek)
    kill = threading.Event()
    progress = macron_ivtc_getmetrics.getmetrics(avspath, scriptsrc, outfile, outext, threads, 
                                    seek, frames, False, ignorecorner=ignorecorner,
                                    avspmacro=True, killevents=[kill])
    target = progress.next()
    pbox = avsp.ProgressBox(max=target, message='Collecting metrics', title='Progress')
    pr = 0
    next = 0
    while True:
        if next<0:
            break
        pr = max(pr, next)
        if not pbox.Update(min(pr, target))[0]: #canceled
            kill.set()
            pbox.Destroy()
            return
        next = progress.next()
    pbox.Destroy()
prefix = options[4]
sortbystrength = options[5]
if not os.path.isabs(prefix):
    prefix = os.path.join(os.path.dirname(outfile), prefix)
msg = macron_ivtc_processmetrics.processmetrics(outfile+outext, prefix, sortbystrength)
avsp.MsgBox(msg)

template = """
slow = 2
display = false
prefix = "{}"
{}
#You should fix borders before processing (fixborders/balanceforders/fillmargins)
#Delogo helps a bit too
src = last#.fixborders(l="d2;d1", r="d2;d1")
ivtc = src.tfm(pp=0, ovr=prefix+"tfmovr.txt").tdecimate(ovr=prefix+"tdcovr.txt")
croph = src.Height()/18*4
inflate = 40
ivtc
ivtcpp_mixedcontent(src, last, prefix+"mixbot.txt", y1=src.Height()-croph, inflate=inflate, slow=slow)
ivtcpp_mixedcontent(src, last, prefix+"mixtop.txt", y2=croph, inflate=inflate, slow=slow)
ivtcpp(fileprefix=prefix, slow=slow, display=display, lsb=false)
"""

script = textwrap.dedent(template).format(prefix, avsp.GetText())
avsp.NewTab(copyselected=False)
avsp.SetText(script)
