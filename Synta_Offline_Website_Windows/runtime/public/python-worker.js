/* This worker runs inside an opaque-origin, network-restricted iframe. */
self.onmessage = async event => {
  const { code, input, runtime } = event.data;
  let remaining = 24000;
  let clipped = false;
  function write(kind, value) {
    const text = String(value) + "\n";
    if (remaining > 0) {
      self.postMessage({ type: "output", kind, text: text.slice(0, remaining) });
      remaining -= text.length;
    }
    if (remaining <= 0 && !clipped) {
      clipped = true;
      self.postMessage({ type: "output", kind: "stderr", text: "\n[Output limited to 24,000 characters.]\n" });
    }
  }

  try {
    importScripts(runtime + "pyodide.js");
    const inputs = input ? input.split(/\r?\n/) : [];
    const py = await loadPyodide({
      indexURL: runtime,
      // Browser prompts are unavailable inside a worker. Each input() consumes one line.
      stdin: () => inputs.length ? inputs.shift() : undefined,
      stdout: value => write("stdout", value),
      stderr: value => write("stderr", value),
    });
    self.postMessage({ type: "ready" });
    try {
      await py.runPythonAsync(code, { filename: "main.py" });
      self.postMessage({ type: "done", ok: true });
    } catch (error) {
      const stack = String(error.message || error);
      const sourceFrames = [...stack.matchAll(/File "main\.py", line (\d+)/g)];
      const start = stack.indexOf('  File "main.py"');
      const traceback = start < 0 ? stack : "Traceback (most recent call last):\n" + stack.slice(start);
      self.postMessage({
        type: "done", ok: false, error: traceback.slice(0, 8000),
        line: Number(sourceFrames.at(-1)?.[1]) || 0,
      });
    }
  } catch (error) {
    self.postMessage({ type: "failed", error: "Could not load the bundled Python runtime. " + String(error.message || error) });
  }
};
