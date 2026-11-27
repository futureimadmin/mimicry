"""Download the OpenVoice v2 tone-colour-converter (~131 MB) into third_party/OpenVoice/checkpoints_v2.

The original S3 links are dead; the files now live on Hugging Face. Usage: python scripts/fetch_models.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "third_party" / "OpenVoice" / "checkpoints_v2" / "converter"
MIN_BYTES = 100 * 1024 * 1024
# (repo, path prefix inside repo) - first is MyShell's official repo, second is a community mirror
SOURCES = [("myshell-ai/OpenVoiceV2", ""), ("rsxdalv/OpenVoiceV2", "checkpoints_v2/")]


def main() -> int:
    if (DEST / "checkpoint.pth").exists() and (DEST / "checkpoint.pth").stat().st_size > MIN_BYTES and (DEST / "config.json").exists():
        print("Model files already present.")
        return 0
    from huggingface_hub import hf_hub_download
    DEST.mkdir(parents=True, exist_ok=True)
    errors = []
    for repo, prefix in SOURCES:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                got = {}
                for name in ("config.json", "checkpoint.pth"):
                    print(f"Downloading {repo}: {prefix}converter/{name} ...", flush=True)
                    got[name] = Path(hf_hub_download(repo_id=repo, filename=f"{prefix}converter/{name}", local_dir=tmp))
                if got["checkpoint.pth"].stat().st_size < MIN_BYTES:
                    raise RuntimeError("checkpoint.pth is too small - download incomplete")
                for name, src in got.items():
                    shutil.copyfile(src, DEST / name)
            print("Model files installed to", DEST)
            return 0
        except Exception as e:  # noqa: BLE001
            errors.append(f"{repo}: {e!r}")
            print(f"  failed: {e!r}", flush=True)
    print("\nCould not download the model automatically:\n  " + "\n  ".join(errors))
    print("\nManual fix: open https://huggingface.co/myshell-ai/OpenVoiceV2/tree/main/converter in a browser,")
    print(f"download checkpoint.pth and config.json, and put both in:\n  {DEST}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
