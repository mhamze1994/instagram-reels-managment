"""Local administrative commands. No authentication secrets are printed or bundled."""
import argparse
import json
from pathlib import Path
import app


def import_folder(root):
    videos = sorted(root.rglob('video.mp4'))
    for video in videos:
        folder = video.parent
        caption = folder / 'caption.txt'
        episode = folder / 'episode.json'
        ep = json.loads(episode.read_text(encoding='utf-8-sig')) if episode.exists() else {}
        cover = next((folder / x for x in ['cover.png', 'cover.jpg'] if (folder / x).exists()), None)
        ident, created = app.ingest(video, cover, ep.get('title') or ep.get('hook') or folder.name,
                                    ep.get('category', 'فوتبال'), caption.read_text(encoding='utf-8-sig') if caption.exists() else '', ep or None)
        print(('Imported ' if created else 'Already present ') + ident + ' ' + folder.name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    imp = sub.add_parser('import-folder')
    imp.add_argument('folder', type=Path)
    args = parser.parse_args()
    app.init_db()
    if args.command == 'import-folder':
        import_folder(args.folder.resolve())
