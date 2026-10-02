// Fills every `a.support-email` with the support address, assembled here so the address never
// appears as text in the page source — harvesters that read raw HTML don't run scripts.
// To change the address, replace the character codes (`[...address].map(c => c.charCodeAt(0))`).
const address = String.fromCharCode(
  97, 112, 112, 45, 115, 117, 112, 112, 111, 114, 116,
  64, 115, 107, 101, 109, 101, 110, 111, 118, 46, 99, 111, 109
);

for (const link of document.querySelectorAll("a.support-email")) {
  link.textContent = address;
  link.href = "mailto:" + address;
}
