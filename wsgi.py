from flask_app import create_app


app = create_app(
    {
        'DEBUG': True,
        'SECRET_KEY': 'this_is_a_joke_0f_a_S3cr3t_K3y',
        'ENV': 'development'
    }
)


if __name__ == '__main__':
    app.run()