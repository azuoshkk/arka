// Capture only: no inference or network on the Raspberry.
class ArkaCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = new Float32Array(320); this.index = 0; }
  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0);
    const input = inputs[0]?.[0];
    if (input) for (const sample of input) {
      this.buffer[this.index++] = sample;
      if (this.index === this.buffer.length) {
        this.port.postMessage(this.buffer, [this.buffer.buffer]);
        this.buffer = new Float32Array(320); this.index = 0;
      }
    }
    return true;
  }
}
registerProcessor('arka-capture', ArkaCapture);
