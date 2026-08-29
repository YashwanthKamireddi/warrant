# Console

A view onto the engine, never a second implementation of it. Every verdict
rendered here came from `warrant.gate.evaluate()`; nothing is re-derived in the
browser.

```
npm install
npm run dev      # proxies /api to http://127.0.0.1:8787
npm run build    # emits dist/, which `warrant serve` mounts automatically
```

Three rules govern the visual language:

1. Chrome is achromatic. Greys carry a slight cool bias so they read as chosen,
   but no hue competes with meaning.
2. Colour is reserved for verdicts. Green, red and amber mean allow, block and
   escalate — never decoration.
3. Gold appears in exactly one place: a signature seal.
