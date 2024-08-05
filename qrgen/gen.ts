import qrcode from 'qrcode-terminal';

// Get the URL from the command line arguments
const url = Deno.args[0];

if (!url) {
  console.log('Usage: node qrgen/gen.ts <url>');
  Deno.exit(1);
}

console.log('QR Code:');
qrcode.generate(url);