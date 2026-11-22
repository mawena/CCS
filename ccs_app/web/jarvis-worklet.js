// Micro de l'oreille de Jarvis (jarvis-ear.js) : passe chaque bloc du micro (mono, à la fréquence
// du contexte audio) au fil principal, qui le rééchantillonne en 16 kHz et l'envoie au relais.
class JarvisCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel?.length) this.port.postMessage(channel.slice(0));
    return true;
  }
}

registerProcessor("jarvis-capture", JarvisCapture);
