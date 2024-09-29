import { Section } from "../Section";
import { IconChevronDown } from "../Icons";
import { THEMES, useTheme } from "../theme";
import { useAutostart } from "../useAutostart";

export const Settings = () => {
  const [theme, setTheme] = useTheme();
  const autostart = useAutostart();

  const handleAutostartChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    autostart.setAutostart(e.target.checked);
  };

  return (
    <>
      <Section
        header=""
        children={
          <div className="flex flex-col gap-4">
            <h2 className="text-2xl font-bold">Theme</h2>
            <p className="text-base-content/50">Saved automatically.</p>

            <div className="flex items-center gap-4 z-10">
              <div className="dropdown">
                <div tabIndex={0} role="button" className="btn m-1 capitalize">
                  {theme}
                  <IconChevronDown />
                </div>
                <ul
                  tabIndex={0}
                  className="dropdown-content menu border-2 bg-base-100 rounded-box border-base-content/10 w-52 p-2 shadow z-20"
                >
                  {THEMES.map((t) => {
                    return (
                      <li onClick={() => setTheme(t)} key={t} value={t}>
                        <a className="capitalize">{t}</a>
                      </li>
                    );
                  })}
                </ul>
              </div>

              <div className="flex gap-4 rounded-box p-4 bg-base-200">
                <div className="badge badge-primary"></div>
                <div className="badge badge-secondary"></div>
                <div className="badge badge-accent"></div>
                <div className="badge badge-neutral"></div>
                <div className="badge badge-info"></div>
                <div className="badge badge-success"></div>
                <div className="badge badge-warning"></div>
                <div className="badge badge-error"></div>
              </div>
            </div>

            <h2 className="text-2xl font-bold mt-4">Auto Start</h2>
            <p className="text-base-content/50">
              Launch Harbor App when your system starts.
            </p>

            <div className="form-control w-52">
              <label className="label cursor-pointer">
                <span className="label-text">Enable Auto Start</span>
                <input
                  type="checkbox"
                  className="toggle"
                  checked={autostart.enabled}
                  disabled={autostart.loading}
                  onChange={handleAutostartChange}
                />
              </label>
            </div>
          </div>
        }
      />
    </>
  );
};
