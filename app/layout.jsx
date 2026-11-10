import './globals.css';

export const metadata = {
  title: 'Commerce Business OS',
  description: 'Products, customers, campaigns and launches in one workspace.',
};

const themeInit = `(function(){try{var t=localStorage.getItem('cos-theme')||'light';document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;

export default function RootLayout({ children }) {
  return (
    <html lang="en" data-theme="light">
      <head><script dangerouslySetInnerHTML={{ __html: themeInit }} /></head>
      <body>{children}</body>
    </html>
  );
}
