async function main() {
  // Launch "bun tauri dev" from the "app" folder
  const cmd = new Deno.Command(
    'bun',
    {
      args: [
        'tauri',
        'dev'
      ],
      stdin: 'inherit',
      stdout: 'inherit',
      stderr: 'inherit',
      cwd: 'app',
    }
  )
  const process = cmd.spawn()

  // Handle termination signals
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    Deno.addSignalListener(signal, () => {
      console.log(`Received ${signal}, terminating child process...`);
      process.kill(signal);
    });
  }

  await process.status;
}

main().catch(console.error);