import React from 'react';
const Link = ({ children, href, onClick, className }) => React.createElement('a', { href, onClick, className }, children);
export default Link;
