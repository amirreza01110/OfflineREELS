from InstantGram import ensure_seed_files, get_media_index, app
import time
from TID import init
from multiprocessing import Process


def InstantInit():
    ensure_seed_files()
    get_media_index()
    app.run(host="0.0.0.0", port=80, debug=False)


def DownloaderInit():
    init()


if __name__ == "__main__":
    try:
        Process(target=InstantInit).start()
        Process(target=DownloaderInit).start()



    except KeyboardInterrupt:
        print("\n👋 Bye!")

