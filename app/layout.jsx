import './globals.css';

export const metadata = {
  title: 'Commerce Business OS',
  description: 'Products, customers, campaigns and launches in one workspace.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en"><body>{children}</body></html>
  );
}
