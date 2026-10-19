# Meterless POWER prompts (copied from meterless.ai/engines.html, 19 Oct 2026)

The Participant Setup Guide calls the 'provider' prompt the implementation contract for the Power rule.

## provider

Add Meterless Runtime to this codebase as an OpenAI-compatible provider, next to the providers it already has.

The contract (Meterless Runtime 0.90.0):
- Provider id meterless, name Meterless Runtime, default base URL http://127.0.0.1:8088/v1. Accept a pasted URL with or without a scheme, /v1, /v1/chat/completions, /v1/models or /healthz, and normalise it to <host>/v1. Never produce /v1/v1.
- Auth is real. Send Authorization: Bearer <token> on every call. The runtime writes the token to <stateDir>/proxy-token. Store it under the key meterless_runtime_token. The placeholder rt-local is rejected.
- Send meterless-app: <a stable lowercase id for this app> on every request, and meterless-scope: user on chat.
- Model ids are routing modes, not models: meterless/<disposition> (auto, fast, deep, cheap, local, fusion), meterless/<class> and meterless/<class>.<disposition>. Read them from GET /v1/models and keep any meterless/* id you don't recognise.
- GET /healthz only proves the process is up. GET /v1/models decides: 401 or 403 is "unauthorized" (show a field to paste the token), 200 with meterless ids is "online", anything else is "offline".
- Auto Detect tries ports 8088, 8090, 8787 and 11434 on 127.0.0.1, localhost and [::1], and saves the first online or unauthorized hit.
- Plain text requests stay a string, exactly like OpenAI. Use a 180 s timeout, because a model load can take minutes.

You are done when a wrong token shows unauthorized (not offline), Auto Detect finds the runtime, and a plain text request on meterless/auto returns a string.

## discovery

Make this codebase's Meterless Runtime provider read its capabilities from the runtime instead of hard-coding them.

- GET /v1/models lists the meterless/* rows, each with a meterless block. Keep unknown meterless/* ids. Show a constant list only until the first probe answers. The endpoints field on a row describes the grammar. It does not prove a route exists.
- GET /v1/meterless/classes is the live state per class. Accept both shapes, {classes: {<id>: {...}}} and {data: [{class, ...}]}, and a bare string state. Map ready → ready; starting, parked, declared or admittable → "may take a moment"; cloud → "leaves the machine"; unavailable → greyed out, showing its why. This overrides the availability from /v1/models. A runtime without this route still gets a working picker.
- chat_carrier on each class says whether POST /v1/chat/completions can return it. On 0.90.0 it is true for text, code, vision and judge, and false for the rest. false means "use another route", not "this machine can't".
- Emit one health event (meterless:health with state, checkedAt, reason and baseUrl) that every screen listens to instead of polling. Any failed request sets offline right away. Going online invalidates discovery.

Build the model picker from this. You are done when the picker shows every class with its live state and reason, and stopping the runtime flips every screen to offline without a reload.

## answer-shapes

Harden this codebase's Meterless Runtime chat client (POST /v1/chat/completions) against every answer shape the runtime sends.

Requests: plain text stays a string. Attachments turn the user turn into parts: image → image_url with a data URL, audio → input_audio with base64 and a format, anything else → file with filename and file_data.

Answers: choices[0].message can carry content as a string; content as an array of parts (text, image_url, audio or output_audio with url or data, input_audio, audio_url, video_url); message.audio beside a string content; or top-level meterless.artifacts[]. Read all of them. Turn bare base64 into a data: URL and the format wav into audio/wav.
- Choose the reader from the response Content-Type, not from the request. A stream: true request can come back as application/json, so parse it as one body. Without res.body.getReader, fall back to res.json().
- SSE: join delta.content strings, read an array delta.content as parts, and send frames carrying meterless.progress to onProgress. Send meterless-trace: on only when something shows progress.
- Code that only reads strings gets a flattened answer: the text, then one "Image: <url>" or "Audio: <url>" line per artifact, with the original parts kept on message.meterless_parts.
- A text answer to a media request is an error (text_instead_of_media). It is never accepted as media.
- A 429 or quota error retries after 2 s, 4 s and 8 s, then surfaces.

Build a small mock server that returns each shape, including stream: true answered as JSON. Write a test per shape and show them passing.

## task-router

Add a task router for Meterless Runtime to this codebase. Make it one pure module with no fetch and no storage, so it can be tested alone.

Meterless model ids are meterless/<class>.<disposition>. Classes: text, code, vision, judge, perception, image, video, speech, transcribe, music, embed. Dispositions: auto, fast, deep, cheap, local, fusion, cluster.

Rules:
- Every call site declares a task, and the task picks the class (for example commentary → text, grade → judge, screenshot → vision, still → image, voice → speech, theme → music). Map our real call sites: [list them, or find them yourself].
- The disposition comes from the user's single pick in Settings. A per-task pin (for example meterless/image.local for stills only) beats both.
- A task never inherits its class from whichever model happens to be selected.
- Attachments change the class only when the task's output is text: audio or video → transcribe, image → vision, PDF or document → perception. "Make a still from this screenshot" stays image.
- Send the meterless-accept header only for the media the route produces (image → image, speech or music → audio, video → video), per request. Never set it globally.
- fusion on a single-core class (video, music, speech, embed) and cluster on vision, perception, transcribe or embed are downgraded to auto before sending, and the downgrade is recorded. Read which classes allow fusion from GET /v1/meterless/modes when it answers; this list is the fallback. cluster on a runtime that marks it unavailable is refused, never swapped for auto.

Expose planRoute(task, attachments) → {id, class, disposition, source, downgrade} and render it as a routing table in Settings. Write a unit test for each rule and show them passing.
