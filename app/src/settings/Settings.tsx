import { Section } from "../Section";
import { IconChevronDown } from "../Icons";
import { THEMES, useTheme } from "../theme";
import { useAutostart } from "../useAutostart";

export const Settings = () => {
  const theme = useTheme();
  const autostart = useAutostart();

  const handleAutostartChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    autostart.setAutostart(e.target.checked);
  };

  return (
    <>
      <Section
        header=""
        children={
          <div className="flex flex-col gap-6">
            <div>
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

            <div>
              <h2 className="text-2xl font-bold">Theme</h2>
              <p className="text-base-content/50">
                Customize the look and feel of Harbor App.
              </p>
            </div>

            <div className="flex items-center gap-4 z-10">
              <div className="dropdown">
                <div tabIndex={0} role="button" className="btn m-1 capitalize">
                  {theme.theme}
                  <IconChevronDown />
                </div>
                <ul
                  tabIndex={0}
                  className="dropdown-content menu border-2 bg-base-100 rounded-box border-base-content/10 w-52 p-2 shadow z-20"
                >
                  {THEMES.map((t) => {
                    return (
                      <li onClick={() => theme.setTheme(t)} key={t} value={t}>
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

              <button className="btn btn-sm" onClick={() => theme.reset()}>Reset</button>
            </div>

            <div className="max-w-xl">
              <h2 className="text-2xl font-bold">Hue</h2>
              <p className="text-base-content/50 mb-4">
                Adjust the hue of the theme color.
              </p>

              <input
                type="range" min="0" max="360" value={theme.hue}
                className="range" onChange={(e) => theme.setHue(parseInt(e.target.value))}
              />
            </div>

            <div className="max-w-xl">
              <h2 className="text-2xl font-bold">Saturation</h2>
              <p className="text-base-content/50 mb-4">
                How vibrant the colors are.
              </p>

              <input
                type="range" min="0" max="100" value={theme.saturation}
                className="range" onChange={(e) => theme.setSaturation(parseInt(e.target.value))}
              />
            </div>

            <div className="max-w-xl">
              <h2 className="text-2xl font-bold">Contrast</h2>
              <p className="text-base-content/50 mb-4">
                The difference between the lightest and darkest colors.
              </p>

              <input
                type="range" min="0" max="200" value={theme.contrast}
                className="range" onChange={(e) => theme.setContrast(parseInt(e.target.value))}
              />
            </div>

            <div className="max-w-xl">
              <h2 className="text-2xl font-bold">Brightness</h2>
              <p className="text-base-content/50 mb-4">
                The overall lightness or darkness of the theme.
              </p>

              <input
                type="range" min="10" max="100" value={theme.brightness}
                className="range" onChange={(e) => theme.setBrightness(parseInt(e.target.value))}
              />
            </div>

            <div className="max-w-xl">
              <h2 className="text-2xl font-bold">Invert</h2>
              <p className="text-base-content/50 mb-4">
                Change the colors to their opposites.
              </p>

              <input
                type="range" min="0" max="100" value={theme.invert}
                className="range" onChange={(e) => theme.setInvert(parseInt(e.target.value))}
              />
            </div>
          </div>
        }
      />
    </>
  );
};
