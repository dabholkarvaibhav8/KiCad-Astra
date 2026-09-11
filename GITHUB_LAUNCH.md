# Publish KiCad Astra on GitHub — browser-only guide

This guide publishes **KiCad Astra 1.0**, built by **Next Builder**, using only a
web browser. You do not need Git, GitHub Desktop, a terminal, or GitLab.

The supplied project fits GitHub's current browser-upload limits: fewer than
100 source files, with every individual file under 25 MiB. GitHub documents a
100-file upload limit and 25 MiB per browser-uploaded file. If a future version
exceeds either limit, move to GitHub Desktop or Git for that release.

Official references: [create a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository),
[upload files in the browser](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository),
[manage releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository), and
[download source archives](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives).

## What you received

The delivery ZIP is:

```text
kicad-astra-v1.0.0.zip
└── kicad-astra/
    ├── README.md
    ├── plugin.json
    ├── main.py
    ├── .github/
    ├── agent/
    ├── kicad/
    ├── ui/
    ├── tests/
    └── ...
```

Extract the ZIP before uploading. The repository must contain the **contents of
`kicad-astra/`** at its root. Do not upload the ZIP itself as the source tree,
and do not create a repository containing only another `kicad-astra/` folder.
The correct GitHub homepage immediately shows `README.md`, `plugin.json`,
`main.py`, `agent/`, `kicad/`, and `ui/`.

## 1. Prepare the upload folder

1. Download `kicad-astra-v1.0.0.zip`.
2. Extract it once.
3. Open the extracted `kicad-astra` folder.
4. Confirm these hidden or dot-prefixed entries are present:
   - `.github/`
   - `.gitattributes`
   - `.gitignore`
5. Confirm there is no `.venv/`, `build/`, `dist/`, API key, board backup, or
   private PCB project in the folder.
6. Keep the original ZIP. You will attach it to the v1.0 release later.

On Windows, turn on **View → Show → Hidden items** in File Explorer if needed.
On macOS Finder, press **Command + Shift + .** to show hidden files. These steps
help you verify the dotfiles before uploading.

## 2. Create the empty repository

Sign in to GitHub, open [github.com/new](https://github.com/new), and use:

| Field | Value |
| --- | --- |
| Owner | Your personal or organization account |
| Repository name | `kicad-astra` |
| Description | `Engineer-reviewed PCB layout and manufacturing preparation for KiCad — built by Next Builder.` |
| Visibility | **Public** if you want anyone to download it |
| Repository template | None |
| Add a README | Leave unchecked |
| Add `.gitignore` | Leave as **None** |
| Choose a license | Leave as **None** |

The package already contains its README, ignore rules, and MIT license. Leaving
those boxes empty avoids duplicate starter files. Select **Create repository**.

## 3. Upload every source file in the browser

On the empty repository's Quick Setup page, choose **uploading an existing
file**. If the repository already has a file, use **Add file → Upload files**.

1. Return to the open `kicad-astra` folder on your computer.
2. Select **everything inside it**, including `.github`, `.gitattributes`, and
   `.gitignore`.
3. Drag the selected contents into GitHub's upload area. GitHub also accepts a
   dragged folder, but selecting the inner contents makes the repository root
   unambiguous.
4. Wait until the upload list stops changing and shows no failed item.
5. In the commit message field, enter:

   ```text
   Release KiCad Astra 1.0 by Next Builder
   ```

6. Choose **Commit directly to the `main` branch** for this first upload.
7. Select **Commit changes**. Depending on the page version, GitHub may label
   the final action **Propose changes**; follow the on-screen commit flow.

GitHub's web uploader does not apply `.gitattributes` conversion rules during
that upload. The delivered files are already normalized, so the first upload
is safe. Use the included CI checks to catch later formatting problems.

## 4. Verify the repository structure

After the commit finishes, inspect the repository homepage. The top level must
show these entries:

```text
.github/       agent/          docs/           icons/          kicad/
examples/      scripts/        support/        tests/          ui/
validation/    README.md       plugin.json     main.py         LICENSE
```

Then check all of the following:

- The README banner renders and says **KiCad Astra** and **Built by Next Builder**.
- `plugin.json` appears at the repository root.
- `agent/astra_client.py` exists.
- `.github/workflows/ci.yml` exists.
- `icons/kicad-astra.png` loads.
- `support/__init__.py` contains `VERSION = "1.0.0"`.
- The **Actions** tab shows the **KiCad Astra checks** workflow.

If everything appears under a second `kicad-astra/` folder, the root is wrong.
Create a fresh empty repository and upload the inner contents again; that is
simpler and safer for the first commit than moving every file in the browser.

## 5. Add the GitHub presentation details

On the repository homepage, use the gear icon beside **About** and enter:

| Setting | Recommended value |
| --- | --- |
| Description | `Engineer-reviewed PCB layout and manufacturing preparation for KiCad.` |
| Website | Your Next Builder product or documentation page, if available |
| Topics | `kicad`, `pcb`, `pcb-design`, `eda`, `routing`, `manufacturing`, `python`, `openai` |
| Releases | Enabled |
| Packages | Optional |
| Deployments | Optional |

Under **Settings → General → Features**, enable **Issues** so the included bug
and feature forms can be used. Enable **Discussions** if you want setup help,
showcases, and roadmap conversation separated from bug reports.

For a social preview, export the repository banner to a 1280 × 640 PNG and
upload it under **Settings → General → Social preview**. The included SVG is
optimized for the README, while GitHub's social card uses a raster image.

## 6. Check the automated workflow

Open **Actions → KiCad Astra checks**. The workflow should start after the
first commit. It runs the repository's Python verification on Linux, Windows,
and macOS and builds the source artifact.

A green workflow confirms only the checks that ran in GitHub's environment. It
does not replace testing with a live KiCad editor, an authorized model account,
or a real manufacturing review. If GitHub asks whether to enable workflows,
review `.github/workflows/ci.yml` and enable it.

## 7. Publish the v1.0 download

Open **Releases → Draft a new release** and enter:

| Field | Value |
| --- | --- |
| Tag | Create new tag `v1.0.0` |
| Target | `main` |
| Release title | `KiCad Astra 1.0` |
| Release asset | `kicad-astra-v1.0.0.zip` |
| Set as latest | Enabled |
| Pre-release | Recommended until the open live acceptance checks are complete |

Paste these release notes:

```markdown
## KiCad Astra 1.0

Built by Next Builder.

KiCad Astra is an engineer-reviewed PCB layout and manufacturing-preparation
workbench for KiCad. Version 1.0 includes structured placement planning,
deterministic local routing, reference-label finishing, native DRC comparison,
atomic checked application, isolated fabrication preflight, and reviewable
Gerber, drill, placement, SVG, report, and checksum outputs.

### Start here

1. Download `kicad-astra-v1.0.0.zip` from **Assets**.
2. Extract it.
3. Open `README.md`.
4. Run the offline demo before connecting a real board.

### Verification boundary

Offline, desktop, adapter, transaction, geometry, native CLI, packaging, and
documentation checks are recorded in `VALIDATION.md`. Live editor/API,
multi-platform discovery, and engineer-owned board acceptance remain open.
Always inspect DRC and fabrication outputs before manufacturing.
```

Drag `kicad-astra-v1.0.0.zip` into the release asset box and wait for the upload
to finish. Select **Save draft** if you want one final review. Select **Publish
release** when the title, tag, notes, checkbox state, and asset are correct.

Once live acceptance is complete, edit the same release, clear **Pre-release**,
and keep it marked as the latest release. Do not create a second `v1.0.0` tag
for the same version.

## 8. Test the public download

Open the repository in a private/incognito window and verify:

1. The repository is publicly visible.
2. The README and banner render.
3. **Releases** shows `KiCad Astra 1.0`.
4. The named asset downloads.
5. The ZIP extracts to one `kicad-astra/` folder.
6. The extracted folder contains `README.md`, `plugin.json`, and `main.py` at
   its first level.
7. The quick-start version command prints `KiCad Astra 1.0.0`.

GitHub also provides **Code → Download ZIP** and generated tag archives. Direct
users to the named release asset when you want them to receive the exact tested
package with its `SHA256SUMS.json` manifest.

## 9. Publish future updates without a terminal

For small edits, open a file on GitHub, select the pencil icon, make the change,
and commit it to a new branch. Open a pull request, wait for checks, then merge.
For a multi-file update, use **Add file → Upload files**, upload the changed
files with the same relative paths, and create a branch when GitHub offers it.

For the next release:

1. Update `support/__init__.py`.
2. Add the new version to `CHANGELOG.md`.
3. Update README and validation evidence.
4. Build a newly named release ZIP.
5. Upload the changed source files.
6. Wait for Actions.
7. Create a new semantic tag, such as `v1.0.1` or `v1.1.0`.
8. Attach the matching ZIP and publish the release.

Never upload API keys, `.env` files, private PCB designs, customer data, board
backups, generated fabrication packages, or your local `.venv` directory.
GitHub may block supported secrets through push protection, but secret review
still belongs in your publishing checklist.

## Final launch checklist

- [ ] Repository is named `kicad-astra`
- [ ] Repository root directly contains `README.md`, `plugin.json`, and `main.py`
- [ ] `.github`, `.gitignore`, and `.gitattributes` are present
- [ ] README banner and icon render
- [ ] Product text says **KiCad Astra**
- [ ] Creator text says **Built by Next Builder**
- [ ] Version text says `1.0.0`
- [ ] No credential, private board, environment, or generated output is present
- [ ] GitHub Actions completed or its failure is understood
- [ ] Release tag is `v1.0.0`
- [ ] Release title is `KiCad Astra 1.0`
- [ ] `kicad-astra-v1.0.0.zip` is attached under Assets
- [ ] Public download was tested in a signed-out browser
