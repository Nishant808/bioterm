import {continueRender, delayRender} from 'remotion';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import '@fontsource/jetbrains-mono/600.css';

// Block the first frame until every weight is decoded, so no frame renders
// with a fallback face.
const handle = delayRender('fonts');
const faces = [
  '400 20px Inter', '500 20px Inter', '600 20px Inter', '700 20px Inter',
  '400 20px "JetBrains Mono"', '500 20px "JetBrains Mono"', '600 20px "JetBrains Mono"',
];
Promise.all(faces.map((f) => document.fonts.load(f)))
  .then(() => document.fonts.ready)
  .then(() => continueRender(handle))
  .catch(() => continueRender(handle));
