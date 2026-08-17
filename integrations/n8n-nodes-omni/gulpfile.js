const path = require('path');
const { task, src, dest } = require('gulp');

// Copy node/credential SVG icons into dist alongside the compiled JS so n8n can
// load them. Standard n8n community-node build step.
task('build:icons', copyIcons);

function copyIcons() {
	const nodeSource = path.resolve('nodes', '**', '*.{png,svg}');
	const nodeDestination = path.resolve('dist', 'nodes');
	src(nodeSource, { allowEmpty: true }).pipe(dest(nodeDestination));

	const credSource = path.resolve('credentials', '**', '*.{png,svg}');
	const credDestination = path.resolve('dist', 'credentials');
	return src(credSource, { allowEmpty: true }).pipe(dest(credDestination));
}
