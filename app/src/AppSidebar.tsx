import { FC, Fragment } from "react";
import { Link, useLocation } from "react-router-dom";

import { ROUTES_LIST } from "./AppRoutes";
import { useServiceList } from "./home/useServiceList";

export const AppSidebarContent: FC = () => {
    const location = useLocation();
    const { services } = useServiceList();
    const runningServices = services.filter((s) => s.isRunning);

    return (
        <Fragment>
            {ROUTES_LIST.map((route) => {
                if (route.sidebar === false) {
                    return null;
                }

                return (
                    <li key={route.id}>
                        <Link
                            to={route.path!}
                            className={`menu-item ${
                                location.pathname === route.path ? "active" : ""
                            }`}
                        >
                            {route.name}
                        </Link>
                    </li>
                );
            })}

            {runningServices.length > 0 && (
                <Fragment>
                    {runningServices.map((service) => (
                        <li key={service.handle}>
                            <Link
                                to={`/services/${service.handle}`}
                                className={`menu-item text-sm ${
                                    location.pathname === `/services/${service.handle}` ? "active" : ""
                                }`}
                            >
                                <span className="inline-block w-2 h-2 rounded-full bg-success shrink-0" />
                                {service.name ?? service.handle}
                            </Link>
                        </li>
                    ))}
                </Fragment>
            )}
        </Fragment>
    );
};
