from multiprocessing import Process
from colorama import Fore

def InstantInit():
    from InstantGram import ensure_seed_files, get_media_index, app
    ensure_seed_files()
    get_media_index()
    app.run(host="0.0.0.0", port=80, debug=False)


def DownloaderInit():
    from TID import init
    init()

def print_banner():
    CYAN = Fore.CYAN
    YELLOW = Fore.YELLOW
    GREEN = Fore.GREEN
    BOLD = "\033[1m"
    RESET = Fore.RESET

    banner = f"""
{CYAN}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║                  {BOLD}{YELLOW}📥  OfflineREELS  📥{RESET}{CYAN}                        ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   {GREEN}[1]{CYAN}  InstantGram + TID(TelegramInstantDownloader)          ║
║      Both download and watch reels at the same time          ║
║                                                              ║
║   {GREEN}[2]{CYAN}  InstantGram only                                      ║
║                                                              ║
║   {GREEN}[3]{CYAN}  Download posts from Instagram only                    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{RESET}
    """
    print(banner)



if __name__ == "__main__":
    while True:
        print_banner()
        choice = input("👉 Enter your choice (1/2/3): ")

        if choice.strip() == "1":
                Process(target=InstantInit).start()
                Process(target=DownloaderInit).start()
                break
        elif choice.strip() == "2":

                Process(target=InstantInit).start()
                break  
        elif choice.strip() == "3":
                print(Fore.LIGHTBLUE_EX)
                print("Make sure you have set the User-script on Tampermonkey")
                print("And you have set the download_directory var in the TID/TID-condig.json to your browser's download directory")
                print(Fore.RESET)
                Process(target=DownloaderInit).start()
                break 
        else:
            print("Choose between 1-3")

