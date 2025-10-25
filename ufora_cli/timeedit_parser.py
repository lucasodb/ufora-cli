import re
from typing import Dict, Tuple, List

def parse_timeedit_file(file_path: str) -> Dict[Tuple[str, int], List[Dict]]:
    """
    Parse a TimeEdit timetable file and return structured course data.
    """
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by date headers like "Ma W 43 20-10-2025"
    date_pattern = r'([A-Z][a-z])\s+W\s+(\d+)\s+(\d{2}-\d{2}-\d{4})'
    
    timetable = {}
    current_week = None
    current_date_str = None
    current_day_courses = []
    
    for line in content.split('\n'):
        line = line.strip()
        
        if not line:
            continue
        
        # Check if this is a date header
        date_match = re.match(date_pattern, line)
        if date_match:
            # Save previous day's courses if any
            if current_date_str and current_week is not None and current_day_courses:
                key = (current_date_str, current_week)
                timetable[key] = current_day_courses
            
            # Start new day
            day_abbr, week_num, date_str = date_match.groups()
            current_week = int(week_num)
            current_date_str = date_str
            current_day_courses = []
            continue
        
        # Check if this is a course line
        # Pattern: HH:MM - HH:MM , CourseCode. CourseName, CourseType, Location, Professors
        course_pattern = r'^(\d{2}:\d{2}\s*-\s*\d{2}:\d{2})\s*,\s*(.*)$'
        course_match = re.match(course_pattern, line)
        
        if course_match and current_date_str and current_week is not None:
            time_slot = course_match.group(1)
            rest_of_line = course_match.group(2)
            
            # Parse the course details
            parts = [p.strip() for p in rest_of_line.split(',')]
            
            course_code = ""
            course_name = ""
            course_type = ""
            location = ""
            professors = []
            
            if parts:
                # First part contains code and name separated by a period
                first_part = parts[0]
                code_name_split = first_part.split('.', 1)
                if len(code_name_split) == 2:
                    course_code = code_name_split[0].strip()
                    course_name = code_name_split[1].strip()
            
            if len(parts) > 1:
                course_type = parts[1].strip()
            
            if len(parts) > 2:
                location = parts[2].strip()
            
            # Collect remaining parts as professors
            if len(parts) > 3:
                for prof_part in parts[3:]:
                    prof_part = prof_part.strip()
                    if prof_part and prof_part.lower() not in ['', 'none']:
                        professors.append(prof_part)
            
            course = {
                'time_slot': time_slot,
                'course_code': course_code,
                'course_name': course_name,
                'course_type': course_type,
                'location': location,
                'professors': professors
            }
            
            current_day_courses.append(course)
    
    # Don't forget the last day
    if current_date_str and current_week is not None and current_day_courses:
        key = (current_date_str, current_week)
        timetable[key] = current_day_courses
    
    return timetable


def save_timetable_json(timetable: Dict, output_path: str):
    """Save timetable to JSON file for persistence."""
    import json
    
    # Convert tuple keys to strings for JSON serialization
    json_data = {f"{date}|W{week}": courses for (date, week), courses in timetable.items()}
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)


def load_timetable_json(json_path: str) -> Dict[Tuple[str, int], List[Dict]]:
    """Load timetable from JSON file."""
    import json
    
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    # Convert back to tuple keys
    timetable = {}
    for key_str, courses in json_data.items():
        date_str, week_str = key_str.split('|')
        week_num = int(week_str[1:])
        timetable[(date_str, week_num)] = courses
    
    return timetable


def display_timetable(timetable: Dict[Tuple[str, int], List[Dict]]):
    """Pretty print the timetable."""
    for (date_str, week), courses in sorted(timetable.items()):
        print(f"\n[W{week}] {date_str}")
        print("=" * 80)
        
        for course in courses:
            print(f"  {course['time_slot']}")
            print(f"    {course['course_code']} - {course['course_name']}")
            print(f"    Type: {course['course_type']}")
            print(f"    Location: {course['location']}")
            if course['professors']:
                print(f"    Professors: {', '.join(course['professors'])}")
            print()
