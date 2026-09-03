# NotePad Texts

A texting app where you write your messages by hand on note pads and send them to phone numbers.

https://github.com/bahretc/Etch-A-Sketch.git

## Features

- **Four pad styles** — lined yellow notepad, blank pad, sticky note, and grid pad
- **Three pen styles** — casual script, quick scrawl, and neat print handwriting fonts
- **Send to any number** — enter a phone number and send; notes tear off the pad with an animation
- **Conversation threads** — every number you text gets its own thread, with each sent note shown as a little pad
- **Open in Messages** — on a phone, one tap opens your real messaging app with the note pre-filled (`sms:` link), so you can actually deliver it
- Conversations are saved in your browser (localStorage), so they survive a refresh

## Running it

It's a static site — no build step. Open `index.html` in a browser, or serve the folder:

```
python3 -m http.server 8000
```

then visit http://localhost:8000.
