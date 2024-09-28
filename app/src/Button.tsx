import { ButtonHTMLAttributes, FC } from 'react';

export const Button: FC<ButtonHTMLAttributes<HTMLButtonElement>> = ({ className, ...rest }) => {
    return <button className={`btn btn-sm ${className}`} {...rest}></button>
}
