// Fills every `a.support-email` with the support address, assembled here so the address never
// appears as text in the page source — harvesters that read raw HTML don't run scripts.
// To change the address, replace the character codes (`[...address].map(c => c.charCodeAt(0))`).
const address = String.fromCharCode(
  109, 105, 110, 105, 109, 97, 108, 46, 109, 100, 46, 115, 117, 112, 112, 111, 114, 116,
  64, 105, 99, 108, 111, 117, 100, 46, 99, 111, 109
);

for (const link of document.querySelectorAll("a.support-email")) {
  link.textContent = address;
  link.href = "mailto:" + address;
}
