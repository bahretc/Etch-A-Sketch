# Installing Safety Eval

This page is for someone who has never installed a programming tool before.
It takes about ten minutes, most of which is waiting. You do not need to know
anything about Python, and you will not have to type any commands.

Everything lands in this one folder. Nothing else on the computer is changed.
To remove the tool later, drag this folder to the trash.

## Windows

1. **Unzip the folder.** Right click the zip file you were sent, choose
   "Extract All", and pick somewhere easy to find such as your Documents
   folder. Open the folder it creates.
2. **Double click `install-windows.bat`.** A black window opens and starts
   printing lines of text. That is normal, and it is the only time you will
   see one.
   - Windows may show a blue "Windows protected your PC" box. Click
     **More info**, then **Run anyway**. This happens for any file that did
     not come from the Microsoft Store.
   - If it tells you Python is missing, follow the four steps it prints, then
     double click `install-windows.bat` again. The one step people miss is
     ticking **Add python.exe to PATH** on the first screen of the Python
     installer.
3. **Wait for it to say Done.** The slow part is the middle, where it
   downloads. Five minutes is normal on office wifi.
4. **Double click `run-app-windows.bat`.** The app opens in its own window,
   titled NCDOT Safety Studies, within a few seconds. Close the window to
   quit; double click the same file to open it again any other day.
   - The first time, Windows Firewall may ask about Python. Click Cancel or
     Allow, either is fine: the app talks only to itself on your own
     computer.

You only run the installer once.

## Mac

1. **Unzip the folder** by double clicking the zip file, then open the folder
   it creates.
2. **Double click `install-mac.command`.** A terminal window opens and starts
   printing lines of text. That is normal.
   - If the Mac says the file "cannot be opened because it is from an
     unidentified developer", right click the file instead, choose **Open**,
     then click **Open** in the box that appears. You only do this once.
   - If it tells you Python is missing, follow the steps it prints, then
     double click `install-mac.command` again.
3. **Wait for it to say Done.**
4. **Double click `run-app-mac.command`.** The app opens in its own window.
   The small terminal window that appears can be closed; the app stays open.

## What the app looks like

A window titled **NCDOT Safety Studies**. On the left, the sidebar: the
Study picker at the top under the page list, then the pages in workflow
order, grouped Start, Crash review, and the study type's own deliverables.
The Overview page walks the workflow step by step and shows what the open
study already has.

## Turning on the AI features

Four parts of the app ask a Claude model for help: the crash review assist,
the QA sweep, the chat tab, and the results text drafting. Everything else
works without them.

They need an API key from https://console.anthropic.com. Once you have one:

- Open the app, find the **AI assist settings** panel on the review page, and
  paste the key into the box. It stays in the app for as long as the app is
  running and is never written to disk, so you paste it again next time.
- If you would rather not paste it each time, ask whoever set up your machine
  to add `ANTHROPIC_API_KEY` to your Windows user environment variables. The
  app picks it up on its own after that.

The review assist never sees an unredacted crash report. It only ever gets
pages the tool has already redacted, and it refuses to run otherwise. Every
answer it gives is a proposal for you to accept or overrule. Nothing it says
is written into a workbook until you decide.

## If something does not work

Run the installer again. It is safe to run any number of times and will
repair a half finished install.

If the app window never appears, a log file named `safety_eval_desktop.log`
in the system temp folder says why; send it along with what you were doing.

Two things commonly show as unavailable in the checklist the installer prints
at the end, and neither stops the main work:

- **LibreOffice** is used to recalculate and print workbooks. Without it those
  two steps report that the file could not be loaded.
- **Chromium** prints the package maps to PDF. Without it the maps are still
  written as web pages you can open in any browser and print yourself.

For the step by step of running a real study, see `docs/13-beta-walkthrough.md`.
