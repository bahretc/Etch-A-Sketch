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

No build step and no dependencies. Either open `index.html` directly in a browser, or run the included server:

```
node server.js
```

then visit http://localhost:8000.

## Sending real SMS (optional)

The server can deliver notes as actual text messages through [Twilio](https://console.twilio.com):

1. Copy `.env.example` to `.env`
2. Fill in `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER` (a free trial account works)
3. Restart `node server.js`

Without credentials the app runs in simulated mode — notes are saved to conversation threads, and you can still deliver one for real with the "Open in Messages" button on a phone.
