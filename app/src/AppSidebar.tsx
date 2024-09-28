import { FC, Fragment } from "react";
import { Link, useLocation } from "react-router-dom";

import { ROUTES_LIST } from "./AppRoutes";

export const AppSidebarContent: FC = () => {
    const location = useLocation();

    return (
        <Fragment>
            {ROUTES_LIST.map((route) => {
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
        </Fragment>
    );
};
