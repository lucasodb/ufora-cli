# Ufora CLI

A command-line tool for accessing UGent course material from Ufora.

## Installation

```bash
# Install the CLI tool
pipx install git+https://github.com/lucasodb/ufora-cli.git

# Install Playwright (required for browser automation)
pipx inject ufora-cli playwright --include-apps

# Install Firefox browser for Playwright
playwright install firefox
```

### Troubleshooting Installation

If you get `command not found` errors after installation:
```bash
# Ensure pipx's binary directory is in your PATH
pipx ensurepath

# Reload your shell configuration
source ~/.bashrc
# or for zsh users:
source ~/.zshrc

# If issues persist, try a clean reinstall
pipx uninstall ufora-cli
pipx install git+https://github.com/lucasodb/ufora-cli.git
pipx inject ufora-cli playwright --include-apps
playwright install firefox
```

If `playwright install firefox` shows OS compatibility warnings, you can safely ignore them - the fallback build will work fine.

## Commands

| Command           | Description                                              
|------------------|----------------------------------------------------------
| `email`      | Set default email to be used when logging in to Ufora.   
| `directory`  | Set base directory where course materials will be downloaded.
| `twofa` | Set the 2fa method you use for logging in to Ufora. The value can either be `app` (default), to use Outlook or an authentication app, or `sms`, to get your code sent via sms. These are the only two supported options at this moment.
| `login` | Login to Ufora. This will let you login via command line, by prompting for your email and password and then running firefox headless to fill in this information. Depending on your set 2fa method, you will then be shown the 2fa code you need to use on your other device, or you will be prompted to give the code you received via sms.
| `courses` | Show your active courses for the current year.
| `materials` | Show the course materials for one of your courses. Pass the ID of the course from the table you get from the `courses` command to select the course you want.
| `download` | Download specific or all course material of a selected course. Pass the ID of the course from the table you get from the `courses` command to select the course you want. When no option is used, the materials will be downloaded in the directory set by the `directory` command, in a subdirectory that is named after the course you are downloading the material from. If you did not set a base directory with the `directory` command, the content will be downloaded under `home/uni`. <br><br> `-d/--dir`: Pass a directory to download the course material in. <br><br> `-h/--here`: Download the course material in the current directory. This is the recommended use of this command: go to the directory you want your files to be in and run this command with the `-h` option.
| `importtimetable` | Import your TimeEdit calendar, and save it to a JSON file. Since TimeEdit doesn't offer an easy way to access your UGent timetable via requests, we use the primitive way of just downloading the current calendar. Since this kind of data doesn't or barely changes, this if fine, and this file should just be updated every new academic year. Go to your calendar on TimeEdit and click on Download > Text, then copy to a text file. Give the path to this file as argument to this command. The data will be parsed and saved to JSON.
| `timetable` | Show the timetable of today's courses. <br><br> `-w/--week`: Show the timetable for the whole week. <br><br> `-c/--compact`: Show a more compact version of the timetable (this just removes the professors column).


## Usage

### First-time setup
```bash
# Set your email (optional, for convenience)
ufora email <your.email@ugent.be>

# Set your base university directory (optional)
ufora directory <path/to/base/directory>

# Set the 2fa method you use for login
ufora twofa <app/sms>

# Login to Ufora
ufora login
```
### Download materials
```bash
# View a list of this year's courses
ufora courses

# View materials for a course
ufora materials 1

# Download materials
ufora download 1
```

### Timetable
```bash
# Import your timetable
ufora importtimetable <path/to/timetable.txt>

# View today's schedule
ufora timetable

# View this week's schedule
ufora timetable --week
```

## Example

### Downloading materials
![Downloading materials](assets/demo-download.gif)

### Displaying timetable
![Displaying timetable](assets/demo-timetable.gif)

## Configuration

Configuration is stored in `~/.config/ufora-cli/`:
- `cookies.pkl` - Authentication cookies
- `config.json` - Settings (email, base directory)
- `timetable.json` - Imported timetable data

## Notes

- Gathering course material can be very slow, depending on how many submodules a course has. Because of the way Ufora fetches content, a separate request needs to be made for every folder on the content page to scrape this folders contents. So, if a course has many submodules, this can take over 10 seconds.
- Currently only one level of nested folders is supported. I have not seen a case where there was more than this, so I did not bother to implement gathering content in a recursive way, but this could be changed in the future if deemed necessary. 
- Other things like 'Announcements' might be added in the future.
- Tip: don't look at the code for too long. It's unpleasant and might give you a headache.