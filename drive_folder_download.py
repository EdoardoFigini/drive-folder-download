import os
import io
import hashlib
import time
import concurrent.futures
import threading
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from utils import *


class FileDiffException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class DownloadProgress:
    def __init__(self) -> None:
        self.progress = 0
        self.byte_progress = 0
        self.byte_size = 0


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def auth():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open("token.json", "w") as token:
                token.write(creds.to_json())
    except RefreshError:
        try:
            os.remove("token.json")
            creds = auth()
        except FileNotFoundError:
            return None
    return creds


def get_files_metadata(service, folder_id: str, relative_path: str):
    try:
        results = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents",
                fields="nextPageToken, files(mimeType, id, name, md5Checksum, modifiedTime, size)",
            )
            .execute()
        )
        items = results.get("files", [])
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []

    for item in items:
        if "relativePath" in item:
            continue
        item["relativePath"] = relative_path
        if item["mimeType"] == "application/vnd.google-apps.folder":
            rel_path = os.path.join(relative_path, item["name"])
            try:
                os.mkdir(rel_path)
            except FileExistsError:
                pass
            finally:
                items += get_files_metadata(service, item["id"], rel_path)
        else:
            print(
                f"{gray}    {os.path.join(item['relativePath'], item['name']).replace(os.getcwd(), '.')}{reset}"
            )
    return items


def get_remote_diff_files(service, files: list):
    items = {"new": [], "diff": [], "stagedForDownload": []}

    padding = (
        max(
            [
                len(x["name"]) + len(x["relativePath"].replace(os.getcwd(), "."))
                for x in files
            ]
        )
        + 5
    )

    for item in files:
        remote_md5 = item["md5Checksum"]
        filename = os.path.join(item["relativePath"], item["name"]).replace(
            os.getcwd(), "."
        )
        print(
            f"{gray}    {filename}" + (padding - len(filename)) * " " + reset, end="\r"
        )
        try:
            with open(os.path.join(item["relativePath"], item["name"]), "rb") as f:
                local_md5 = hashlib.md5(f.read()).hexdigest()

            if local_md5 != remote_md5:
                items["diff"].append(item)
        except FileNotFoundError:
            items["new"].append(item)

    print(padding * " ", end="\r")
    return items


def threaded_download(file, lock, creds):
    try:
        with lock:
            file["progress"] = DownloadProgress()
            file["progress"].byte_size = int(file["size"])
        service = build("drive", "v3", credentials=creds)
        request = service.files().get_media(fileId=file["id"])
        file_handle = io.BytesIO()
        downloader = MediaIoBaseDownload(
            file_handle, request, chunksize=4 * 1024 * 1024
        )
        done = False
        while not done:
            status, done = downloader.next_chunk(num_retries=8)
            with lock:
                file["progress"].progress = int(status.progress() * 100)
                file["progress"].byte_progress = round(
                    float(status.resumable_progress) / 1024, 2
                )
        with open(os.path.join(file["relativePath"], file["name"]), "wb") as f:
            f.write(file_handle.getvalue())
    except KeyboardInterrupt:
        print_err("KeyboardInterrupt")


def print_download_status(files, futures, lock):
    while [future for future in futures if not future.running()]:
        time.sleep(0.5)
    while [future for future in futures if not future.done()]:
        for file in files:
            with lock:
                finished = file["progress"].progress >= 100
                prog = file["progress"]

            if finished:
                print_ok(
                    blue + os.path.join(file["relativePath"], file["name"]) + reset,
                    end="\n",
                )
            else:
                print_info(
                    os.path.join(file["relativePath"], file["name"]),
                    end="\n",
                )
            print_progress_percent(prog.progress, 50, end="\t")
            if finished:
                print(
                    blue
                    + f"[{sizeof_fmt(prog.byte_size)} / {sizeof_fmt(prog.byte_size)}]"
                    + reset
                )
            else:
                print(
                    f"[{sizeof_fmt(prog.byte_progress)} / {sizeof_fmt(prog.byte_size)}]"
                )
        time.sleep(1)
        sys.stdout.write(2 * len(files) * CLEAN_LINE)
        sys.stdout.flush()


def download_all(files, lock, creds):
    if files:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            print_info("Downloading files:")
            futures = {
                executor.submit(threaded_download, file, lock, creds) for file in files
            }

            print_download_status(files, futures, lock)

            concurrent.futures.wait(futures)

        for file in files:
            print_ok(
                blue + os.path.join(file["relativePath"], file["name"]) + reset,
                end="\n",
            )
            print_progress_percent(file["progress"].progress, 50, end="\t")
            print(
                blue
                + f"[{sizeof_fmt(file['progress'].byte_size)} / {sizeof_fmt(file['progress'].byte_size)}]"
                + reset
            )


def show_prompt(files_dict):
    all = False
    for file in files_dict["diff"]:
        valid = False
        if not all:
            while not valid:
                print_warn("Conflict")
                choice = input(
                    f"    Conflict found for file {file['name']}. Overwrite?\n    [Y] yes, [N] no, [A] yes to all, [B] keep both: "
                )[0]
                match choice.lower():
                    case "a":
                        all = True
                        files_dict["stagedForDownload"].append(file)
                        valid = True
                    case "n":
                        valid = True
                    case "y":
                        files_dict["stagedForDownload"].append(file)
                        valid = True
                    case "b":
                        name, extension = file["name"].split(".", 1)
                        index = len(
                            [
                                x
                                for x in os.listdir(file["relativePath"])
                                if x.startswith(name)
                            ]
                        )
                        file["name"] = f"{name}.{index:03}.{extension}"
                        files_dict["stagedForDownload"].append(file)
                        valid = True
                    case _:
                        valid = False
        else:
            files_dict["stagedForDownload"].append(file)


def main():
    try:
        print("==========[GOOGLE DRIVE SYNC]==========")
        root = os.getcwd()
        try:
            with open(os.path.join(root, ".id")) as f:
                folder_id = f.read()
        except FileNotFoundError:
            print_err(
                "Couldn't find '.id' file in this directory. Make sure you correctly initialized the Google Drive Connection"
            )
            return
        os.chdir(os.path.dirname(__file__))

        print_info("Authorizing...")
        creds = auth()
        if creds is None:
            print_err("Failed to authorize")
            return
        service = build("drive", "v3", credentials=creds)
        print_ok("Done")

        os.chdir(root)

        print_info("Listing files...")
        items = get_files_metadata(service, folder_id.strip(), root)

        print_info("Checking for out of date files")

        files_dict = get_remote_diff_files(
            service,
            [x for x in items if x["mimeType"] != "application/vnd.google-apps.folder"],
        )
        if files_dict["new"]:
            print_info(f"{len(files_dict['new'])} new files:")
            for file in files_dict["new"]:
                print(
                    green
                    + f"    {os.path.join(file['relativePath'], file['name'])}"
                    + reset
                )
        if files_dict["diff"]:
            print_info(f"{len(files_dict['diff'])} out of date files:")
            for file in files_dict["diff"]:
                print(
                    yellow
                    + f"\t{os.path.join(file['relativePath'], file['name'])}"
                    + reset
                )

        lock = threading.Lock()
        req_lock = threading.Lock()
        download_all(files_dict["new"], lock, creds)

        if files_dict["diff"]:
            show_prompt(files_dict)

        download_all(files_dict["stagedForDownload"], lock, creds)

        print_ok("Up to date")
    except KeyboardInterrupt:
        print_err("KeyboardInterrupt")
        return


if __name__ == "__main__":
    main()
