import { IconChevronDown } from "../Icons";
import { Section } from "../Section";
import { THEMES, useTheme } from "../theme";

export const Settings = () => {
  const [theme, setTheme] = useTheme();

  return (
    <>
      <Section
        header=""
        children={
          <div className="flex flex-col gap-4">
            <h2 className="text-2xl font-bold">Theme</h2>
            <p>Saved automatically</p>

            <div className="flex items-center gap-4">
              <div className="dropdown">
                <div tabIndex={0} role="button" className="btn m-1 capitalize">
                  {theme}
                  <IconChevronDown />
                </div>
                <ul
                  tabIndex={0}
                  className="dropdown-content menu border-2 rounded-box border-base-content/10 w-52 p-2 shadow"
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
          </div>
        }
      />
    </>
  );
};
