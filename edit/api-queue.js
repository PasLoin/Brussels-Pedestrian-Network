const NULL_BODY = new Set([101, 103, 204, 205, 304]);

function abortError() {
  try { return new DOMException("The operation was aborted.", "AbortError"); } catch {
    const err = new Error("The operation was aborted.");
    err.name = "AbortError";
    return err;
  }
}

async function buffered(response) {
  const body = NULL_BODY.has(response.status) ? null : await response.arrayBuffer();
  return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
}

export function limitConcurrency(fetchImpl, { max = 2, matches = () => true, onWaiting = () => {} } = {}) {
  let running = 0;
  const waiting = [];
  const report = () => onWaiting(waiting.length);
  const next = () => {
    while (running < max && waiting.length) {
      const job = waiting.shift();
      if (job.cancelled) continue;
      running += 1;
      job.start();
    }
    report();
  };
  return function limitedFetch(input, init) {
    const url = typeof input === "string" ? input : input && input.url;
    if (!matches(url)) return fetchImpl(input, init);
    const signal = (init && init.signal) || (input && input.signal) || null;
    if (signal && signal.aborted) return Promise.reject(abortError());
    return new Promise((resolve, reject) => {
      const job = { cancelled: false };
      const onAbort = () => {
        if (job.started) return;
        job.cancelled = true;
        const i = waiting.indexOf(job);
        if (i >= 0) waiting.splice(i, 1);
        report();
        reject(abortError());
      };
      job.start = async () => {
        job.started = true;
        if (signal) signal.removeEventListener("abort", onAbort);
        try {
          const response = await fetchImpl(input, init);
          resolve(await buffered(response));
        } catch (err) {
          reject(err);
        } finally {
          running -= 1;
          next();
        }
      };
      if (signal) signal.addEventListener("abort", onAbort, { once: true });
      waiting.push(job);
      next();
    });
  };
}
