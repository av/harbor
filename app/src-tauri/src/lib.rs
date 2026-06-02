use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_autostart::MacosLauncher;

mod setup;
#[cfg(desktop)]
mod tray;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default();

    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let _ = show_window(app);
        }));
    }

    builder
        .setup(|app| {
            #[cfg(all(desktop))]
            {
                let handle = app.handle();
                tray::create_tray(handle)?;
            }
            Ok(())
        })
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_window_state::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                #[cfg(not(target_os = "macos"))]
                {
                    let _ = window.hide();
                }

                #[cfg(target_os = "macos")]
                {
                    let _ = tauri::AppHandle::hide(&window.app_handle());
                }
                api.prevent_close();
            }
            _ => {}
        })
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_pty::init())
        .manage(setup::SetupState::default())
        .invoke_handler(tauri::generate_handler![
            setup::detect_harbor_setup,
            setup::get_harbor_wsl_distro,
            setup::start_harbor_setup,
            setup::cancel_harbor_setup,
            setup::write_harbor_setup_input,
            setup::verify_harbor_cli,
            setup::configure_first_run_stack,
            setup::start_first_run_stack,
            setup::verify_first_run_stack,
            setup::open_webui,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app.try_state::<setup::SetupState>() {
                    state.kill_running_process();
                }
            }
        });
}

fn show_window(app: &AppHandle) {
    let windows = app.webview_windows();

    if let Some(window) = windows.values().next() {
        let _ = window.show();
        let _ = window.set_focus();
    }
}
